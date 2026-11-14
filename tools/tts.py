"""自影 · 配音（可替换的语音合成）

在 autoreel.config.json 的 voice.provider 里选择：
  volcengine  火山引擎豆包语音（抖音、剪映同源音色；需要密钥，按量付费，可商用）
  cosyvoice   CosyVoice 离线配音（阿里开源，Apache-2.0；默认 Fun-CosyVoice3-0.5B，支持情绪、语速指令）
  sherpa      sherpa-onnx 轻量离线配音（kokoro / melo / baker，速度最快，没有情绪控制）
  auto        有火山引擎配置就用火山引擎，否则用 CosyVoice，都不可用时退回 sherpa

对外只有一个函数 synth(lines, voice, target)，lines 是字符串或 {"text", "mood", "pace"}，返回 (audio, sample_rate, times, speed)；
synth.last 里还有 sents（每句的文字和起止秒数，字幕用）和 report（清晰度检查结果）。

怎么让配音好听：
  1. 逐句合成：长段落拆成句子再合成，减少吞字、漏字；超过 40 字的句子在逗号处再拆开。
  2. 情绪（mood）：每段可以指定语气，见 MOODS；CosyVoice3 用语气指令，火山引擎用情感参数或语音指令。
  3. 语速（pace）：慢 / 中 / 快，用模型自己的语速参数调，不做事后硬加速（硬加速会让吐字发糊）。
  4. 节奏：句号、问号、感叹号、省略号后的停顿长短不同，段与段之间停得更久。
  5. 读法：稿子按字幕的样子写（11月12日、6.3%、9970亿），配音前由 textnorm.spoken 自动转成读法，字幕照原样显示；
     自动判断不了的写 {显示|读法}，例如 {11.12|十一月十二日}；多音字用 {字|拼音}，例如 {行|háng}；**重点** 会加重语气（CosyVoice3）。
  6. 清晰度检查：用语音识别把每句转回文字和原稿比对，错得多就换随机种子重做，最多 3 次，留最好的一版。
  7. 响度：去低频噪声、轻度压缩、响度统一到 -16 LUFS（短视频平台常用标准）。
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textnorm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 24000  # 统一输出采样率
MAX_SPEED = 1.12  # 整体最多提速 12%，再快吐字就不清楚了，应该删稿
QC_RETRY = 0.08   # 字错率超过 8% 就重做这一句
QC_TRIES = 3

# 语气：CosyVoice3 指令 / 火山引擎 1.0 情感 / 默认语速系数
MOODS = {
    "平稳": ("", "neutral", 1.0),
    "轻快": ("请用轻快、愉悦的语气说这句话。", "happy", 1.03),
    "严肃": ("请用严肃、沉稳的语气说这句话。", "neutral", 0.97),
    "沉重": ("请用低沉、惋惜的语气说这句话。", "sad", 0.94),
    "温暖": ("请用温柔、亲切的语气说这句话。", "neutral", 0.97),
    "惊讶": ("请用惊讶、好奇的语气说这句话。", "surprised", 1.0),
    "激昂": ("请用激动、有力的语气说这句话。", "excited", 1.04),
    "悬念": ("请用神秘、引人好奇的语气，稍微放慢一点说这句话。", "neutral", 0.95),
}
PACE = {"慢": 0.92, "中": 1.0, "快": 1.07}
# 句末停顿（秒）
PAUSE = {"。": 0.30, "！": 0.32, "？": 0.38, "；": 0.22, "…": 0.50, "，": 0.12}
GAP_LINE = 0.50   # 段与段之间
LEAD = 0.30       # 开头留白


# ───────── 文字处理 ─────────
_INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")


def _cv3_pinyin(py):
    """háng → [h][áng]；拆不出来返回 None。"""
    out = []
    for syl in py.split():
        ini = next((i for i in _INITIALS if syl.startswith(i) and len(syl) > len(i)), "")
        fin = syl[len(ini):]
        if not fin:
            return None
        out.append((f"[{ini}]" if ini else "") + f"[{fin}]")
    return "".join(out)


def render_text(text, provider):
    """把稿子里的标记换成各引擎能理解的写法。"""
    def pron(m):
        chars, py = m.group(1), m.group(2).strip()
        if provider == "cosyvoice":
            tok = _cv3_pinyin(py)
            if tok and len(py.split()) == len(chars):
                return tok
        return chars
    text = re.sub(r"\{([^{}|]+)\|([^{}]*)\}", pron, text)
    if provider == "cosyvoice":
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    else:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\[[a-z_\-]+\]", "", text)
    text = text.replace("：", "，").replace("——", "，")
    return text


def display_text(text):
    """字幕显示用：去掉所有配音标记。"""
    text = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"\[[a-z_\-]+\]|</?strong>", "", text)


def split_sentences(text, max_len=40):
    """按句号、问号、感叹号、分号、省略号拆句；太长的句子在逗号处再拆。返回 [(句子, 句末停顿秒数)]。"""
    text = re.sub(r"…+|\.\.\.+", "…", text.strip())
    parts = re.findall(r"[^。！？；…!?;]+[。！？；…!?;]*", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        end = p[-1]
        pause = PAUSE.get({"!": "！", "?": "？", ";": "；"}.get(end, end), 0.25)
        if len(display_text(p)) > max_len:
            subs = re.findall(r"[^，,]+[，,]?", p)
            buf = ""
            for s in subs:
                if buf and len(display_text(buf + s)) > max_len:
                    out.append((buf, PAUSE["，"] + 0.05))
                    buf = ""
                buf += s
            if buf:
                out.append((buf, pause))
        else:
            out.append((p, pause))
    return out or [(text, 0.25)]


# ───────── 音频工具 ─────────
def _to_sr(path):
    """读入任意音频文件（wav/mp3），转为 24kHz 单声道 float32。"""
    out = path + ".24k.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "1", "-ar", str(SR), out], check=True)
    a, _ = sf.read(out, dtype="float32")
    os.remove(out)
    return a


def _trim(a, thr=0.03, keep=0.06):
    """去掉句子前后多余的静音，停顿统一由 PAUSE 控制。"""
    if len(a) == 0:
        return a
    win = int(SR * 0.01)
    e = np.sqrt(np.convolve(a ** 2, np.ones(win) / win, "same"))
    idx = np.where(e > thr * e.max())[0] if e.max() > 0 else []
    if len(idx) == 0:
        return a
    s, t = max(0, idx[0] - int(keep * SR)), min(len(a), idx[-1] + int(keep * SR))
    a = a[s:t].copy()
    f = min(len(a) // 2, int(0.008 * SR))
    if f > 0:
        a[:f] *= np.linspace(0, 1, f)
        a[-f:] *= np.linspace(1, 0, f)
    return a


def _master(a):
    """去低频噪声 → 轻度压缩 → 响度统一到 -16 LUFS，峰值不超过 -1.5 dBTP。"""
    with tempfile.TemporaryDirectory() as d:
        src, dst = f"{d}/a.wav", f"{d}/b.wav"
        sf.write(src, a, SR)
        af = "highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=90:makeup=1,loudnorm=I=-16:TP=-1.5:LRA=9"
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-af", af, "-ar", str(SR), dst])
        if r.returncode != 0:
            return a / (np.abs(a).max() + 1e-6) * 0.9
        b, _ = sf.read(dst, dtype="float32")
    return b[: len(a)] if len(b) >= len(a) else np.pad(b, (0, len(a) - len(b)))


# ───────── 火山引擎豆包语音（HTTP 单向流式接口 V3） ─────────
def volc_available(v):
    c = v.get("volcengine") or {}
    return bool(c.get("app_id") and c.get("speaker") and (c.get("access_key") or os.environ.get("VOLC_TTS_ACCESS_KEY") or c.get("via_proxy")))


def _volc_one(job, c):
    ins, emo, _ = MOODS.get(job.get("mood") or "平稳", MOODS["平稳"])
    rate = int(round((job["speed"] - 1.0) * 100))  # speech_rate：0 为正常，100 为 2 倍速，-50 为 0.5 倍速
    audio_params = {"format": "mp3", "sample_rate": SR, "speech_rate": max(-50, min(100, rate))}
    res = c.get("resource_id", "seed-tts-1.0")
    additions = {}
    if c.get("emotion", True) and emo != "neutral" and not res.startswith("seed-tts-2"):
        audio_params.update({"emotion": emo, "emotion_scale": int(c.get("emotion_scale", 3))})  # 仅多情感音色生效
    if res.startswith("seed-tts-2") and ins:
        additions["context_texts"] = [ins]  # 豆包语音 2.0 的语音指令
    body = {"user": {"uid": "autoreel"},
            "req_params": {"text": job["text"], "speaker": c["speaker"], "audio_params": audio_params}}
    if additions:
        body["req_params"]["additions"] = json.dumps(additions, ensure_ascii=False)
    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": str(c["app_id"]),
        "X-Api-Resource-Id": res,
        # 云端环境可把密钥存为网络密钥，由代理自动加到 X-Api-Access-Key 请求头里（via_proxy: true 时这里留空）
        "X-Api-Access-Key": c.get("access_key") or os.environ.get("VOLC_TTS_ACCESS_KEY", "placeholder"),
    }
    req = urllib.request.Request(c.get("endpoint", "https://openspeech.bytedance.com/api/v3/tts/unidirectional"),
                                 data=json.dumps(body).encode(), headers=headers, method="POST")
    chunks = []
    with urllib.request.urlopen(req, timeout=120) as r:
        for line in r.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue
            j = json.loads(line)
            if j.get("data"):
                chunks.append(base64.b64decode(j["data"]))
            elif j.get("code") not in (0, 20000000, None):
                raise RuntimeError(f"火山引擎返回错误：{j.get('code')} {j.get('message')}")
    if not chunks:
        raise RuntimeError("火山引擎没有返回音频（检查 app_id、密钥、音色是否已开通）")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"".join(chunks))
    try:
        return _to_sr(f.name)
    finally:
        os.remove(f.name)


def _volc_jobs(jobs, v):
    c = v["volcengine"]
    return [_volc_one(j, c) for j in jobs]


# ───────── CosyVoice（独立的 Python 3.10 环境里运行，见 setup.sh） ─────────
COSY_DIR = os.environ.get("COSYVOICE_HOME", os.path.join(HERE, "cosyvoice"))
VOICES = os.path.join(HERE, "voices")


def cosy_available(v=None):
    c = (v or {}).get("cosyvoice") or {}
    model = c.get("model", "Fun-CosyVoice3-0.5B")
    return (os.path.exists(os.path.join(COSY_DIR, "venv", "bin", "python")) and os.path.isdir(os.path.join(COSY_DIR, "CosyVoice"))
            and os.path.isdir(os.path.join(COSY_DIR, "pretrained_models", model)))


def _cosy_prompt(c):
    """参考录音：优先用配置里的 prompt_wav（你自己的声音），否则用 tools/voices/<voice>/ 里的内置音色。"""
    root = os.path.dirname(HERE)
    if c.get("prompt_wav"):
        p = c["prompt_wav"] if os.path.isabs(c["prompt_wav"]) else os.path.join(root, c["prompt_wav"])
        return p, c.get("prompt_text", "")
    d = os.path.join(VOICES, c.get("voice", "女声"))
    return os.path.join(d, "prompt.wav"), open(os.path.join(d, "prompt.txt"), encoding="utf-8").read().strip()


def _cosy_jobs(jobs, v):
    c = v.get("cosyvoice") or {}
    model = c.get("model", "Fun-CosyVoice3-0.5B")
    lines = []
    if model.startswith("CosyVoice-300M-SFT"):
        lines = [{"text": j["text"], "speaker": c.get("speaker", "中文女"), "speed": j["speed"], "seed": j["seed"]} for j in jobs]
    else:
        pw, pt = _cosy_prompt(c)
        for j in jobs:
            ins = MOODS.get(j.get("mood") or "平稳", MOODS["平稳"])[0] if c.get("emotion", True) else ""
            lines.append({"text": j["text"], "prompt_wav": pw, "prompt_text": pt, "instruct": ins, "speed": j["speed"], "seed": j["seed"]})
    with tempfile.TemporaryDirectory() as d:
        jf = os.path.join(d, "job.json")
        json.dump({"model": model, "out": d, "lines": lines}, open(jf, "w"), ensure_ascii=False)
        r = subprocess.run([os.path.join(COSY_DIR, "venv", "bin", "python"), os.path.join(HERE, "cosy_worker.py"), jf],
                           env={**os.environ, "COSYVOICE_HOME": COSY_DIR}, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "CosyVoice 运行失败")
        return [_to_sr(os.path.join(d, f"{i:03d}.wav")) for i in range(len(lines))]


# ───────── sherpa-onnx（kokoro / melo / baker） ─────────
_SHERPA = {}


def _sherpa_jobs(jobs, v):
    sys.path.insert(0, HERE)
    from tts2 import make
    c = v.get("sherpa") or {}
    kind = c.get("kind", "kokoro")
    if kind not in _SHERPA:
        _SHERPA[kind] = make(kind)
    tts, out = _SHERPA[kind], []
    for j in jobs:
        a = tts.generate(j["text"], sid=int(c.get("speaker", 3)), speed=float(c.get("speed", 1.0)) * j["speed"])
        x = np.array(a.samples, dtype=np.float32)
        if a.sample_rate != SR:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, x, a.sample_rate)
            x = _to_sr(f.name)
            os.remove(f.name)
        out.append(x)
    return out


ENGINES = {"volcengine": _volc_jobs, "cosyvoice": _cosy_jobs, "sherpa": _sherpa_jobs}


def pick(v):
    p = v.get("provider", "auto")
    if p != "auto":
        return p
    if volc_available(v):
        return "volcengine"
    if cosy_available(v):
        return "cosyvoice"
    return "sherpa"


# ───────── 主流程 ─────────
def _jobs(lines, provider, speed, seed=0):
    jobs = []
    for li, ln in enumerate(lines):
        ln = {"text": ln} if isinstance(ln, str) else ln
        mood = ln.get("mood") or "平稳"
        base = MOODS.get(mood, MOODS["平稳"])[2] * PACE.get(ln.get("pace") or "中", 1.0)
        for si, (s, pause) in enumerate(split_sentences(ln["text"])):
            say = textnorm.spoken(s)  # 稿子按字幕写，这里转成读法（数字、日期、百分号……）
            jobs.append({"line": li, "raw": s, "say": say, "text": render_text(say, provider), "mood": mood, "pause": pause,
                         "speed": round(base * speed, 3), "seed": seed + li * 31 + si})
    return jobs


def _run(provider, jobs, voice):
    return [_trim(a) for a in ENGINES[provider](jobs, voice)]


def _qc_pass(provider, jobs, segs, voice, qc, log):
    """清晰度检查：错得多的句子换随机种子重做，留字错率最低的一版。"""
    if qc is None:
        return [None] * len(jobs)
    res = [qc.check(a, j["say"], SR) for a, j in zip(segs, jobs)]
    for attempt in range(1, QC_TRIES):
        bad = [k for k, r in enumerate(res) if r and r["cer"] > QC_RETRY]
        if not bad:
            break
        log(f"清晰度：{len(bad)} 句没念清楚，第 {attempt} 次重做")
        redo = [{**jobs[k], "seed": jobs[k]["seed"] + 1000 * attempt} for k in bad]
        try:
            new = _run(provider, redo, voice)
        except Exception as e:
            log(f"清晰度：重做失败（{e}），保留原来的版本")
            break
        for k, a in zip(bad, new):
            r = qc.check(a, jobs[k]["say"], SR)
            if r["cer"] < res[k]["cer"]:
                segs[k], res[k] = a, r
    return res


def synth(lines, voice, target=90, min_speed=1.0, max_speed=MAX_SPEED):
    log = lambda m: print(m, file=sys.stderr)
    provider = pick(voice)
    try:
        import voice_qc
        qc = voice_qc.load() if voice.get("qc", True) else None
    except Exception:
        qc = None

    def attempt(p, speed):
        jobs = _jobs(lines, p, speed)
        return jobs, _run(p, jobs, voice)

    try:
        jobs, segs = attempt(provider, 1.0)
    except Exception as e:
        if provider == "sherpa" or voice.get("provider") not in ("auto", None):
            raise
        log(f"配音：{provider} 失败（{e}），退回 sherpa")
        provider = "sherpa"
        jobs, segs = attempt(provider, 1.0)

    def total(segs, jobs):
        return LEAD + sum(len(a) / SR + j["pause"] for a, j in zip(segs, jobs)) + GAP_LINE * (len(lines) - 1)

    natural = total(segs, jobs)
    speed = 1.0
    if natural > target - 0.6:  # 太长：用模型自己的语速参数整体提速（不超过 MAX_SPEED），再长就要删稿
        speed = min(max_speed, natural / (target - 0.6))
        log(f"配音：正常语速 {natural:.1f}s 超过 {target - 0.6:.0f}s，整体提速到 x{speed:.2f} 重新合成")
        jobs, segs = attempt(provider, speed)
        if total(segs, jobs) > target - 0.6:
            log(f"提醒：提速到 x{speed:.2f} 后仍有 {total(segs, jobs):.1f}s，请把 say 删短（语速再快会吐字不清）")

    res = _qc_pass(provider, jobs, segs, voice, qc, log)

    out, times, sents, t = [np.zeros(int(LEAD * SR), np.float32)], [], [], LEAD
    for li in range(len(lines)):
        ks = [k for k, j in enumerate(jobs) if j["line"] == li]
        start = t
        for n, k in enumerate(ks):
            a = segs[k]
            sents.append((li, display_text(jobs[k]["raw"]), t, t + len(a) / SR))
            out.append(a)
            t += len(a) / SR
            if n < len(ks) - 1:
                p = jobs[k]["pause"]
                out.append(np.zeros(int(p * SR), np.float32))
                t += p
        times.append((start, t))
        gap = GAP_LINE if li < len(lines) - 1 else 0.3
        out.append(np.zeros(int(gap * SR), np.float32))
        t += gap
    audio = _master(np.concatenate(out))

    checked = [(j, r) for j, r in zip(jobs, res) if r]
    report = {"provider": provider, "speed": round(speed, 3), "sentences": len(jobs), "checked": len(checked)}
    if checked:
        report["cer"] = round(float(np.mean([r["cer"] for _, r in checked])), 3)
        report["unclear"] = [{"line": j["line"], "text": r["diff"], "heard": r["heard"], "cer": r["cer"]}
                             for j, r in checked if r["cer"] > QC_RETRY]
    synth.last = {"sents": sents, "report": report}
    msg = f"配音：{provider}，{len(jobs)} 句，语速 x{speed:.2f}"
    if checked:
        msg += f"，清晰度检查平均字错率 {report['cer'] * 100:.1f}%"
        for u in report["unclear"]:
            msg += f"\n提醒：第 {u['line'] + 1} 段这句可能没念清楚（〔〕处）：{u['text']}  识别成「{u['heard']}」"
    elif qc is None:
        msg += "（没有识别模型，跳过清晰度检查）"
    log(msg)
    return audio, SR, times, speed


synth.last = {"sents": [], "report": {}}
