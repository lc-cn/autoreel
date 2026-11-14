"""自影 · 配音（可替换的语音合成）

在 autoreel.config.json 的 voice.provider 里选择：
  volcengine  火山引擎豆包语音（抖音、剪映同源音色；需要密钥，按量付费，可商用）
  cosyvoice   CosyVoice 离线配音（阿里开源，Apache-2.0；无显卡时较慢）
  sherpa      sherpa-onnx 轻量离线配音（kokoro / melo / baker，速度最快）
  auto        有火山引擎密钥就用火山引擎，否则用 CosyVoice，都不可用时退回 sherpa

对外只有一个函数 synth(lines, voice, target, min_speed)，返回 (audio, sample_rate, times, speed)：
每行单独合成，按需整体加速（ffmpeg atempo，不变调），times 是每行在整段音频里的起止秒数。
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 24000  # 统一输出采样率
GAP = 0.18  # 句间停顿（秒）


def _to_sr(path):
    """读入任意音频文件（wav/mp3），转为 24kHz 单声道 float32。"""
    out = path + ".24k.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "1", "-ar", str(SR), out], check=True)
    a, _ = sf.read(out, dtype="float32")
    os.remove(out)
    return a


def _atempo(a, factor):
    if abs(factor - 1.0) < 0.01:
        return a
    with tempfile.TemporaryDirectory() as d:
        src, dst = f"{d}/a.wav", f"{d}/b.wav"
        sf.write(src, a, SR)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-filter:a", f"atempo={factor:.4f}", dst], check=True)
        b, _ = sf.read(dst, dtype="float32")
    return b


# ───────── 火山引擎豆包语音（HTTP 单向流式接口 V3） ─────────
def volc_available(v):
    c = v.get("volcengine") or {}
    return bool(c.get("app_id") and (c.get("access_key") or os.environ.get("VOLC_TTS_ACCESS_KEY") or c.get("via_proxy")))


def _volc_one(text, c):
    body = {
        "user": {"uid": "autoreel"},
        "req_params": {
            "text": text,
            "speaker": c["speaker"],
            "audio_params": {"format": "mp3", "sample_rate": SR, "speech_rate": int(c.get("speech_rate", 0))},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": str(c["app_id"]),
        "X-Api-Resource-Id": c.get("resource_id", "seed-tts-1.0"),
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


def _volc_lines(lines, v):
    c = v["volcengine"]
    if not c.get("speaker"):
        raise RuntimeError("voice.volcengine.speaker 没有填写音色 ID")
    return [_volc_one(t, c) for t in lines]


# ───────── CosyVoice（独立的 Python 3.10 环境里运行，见 setup.sh） ─────────
COSY_DIR = os.environ.get("COSYVOICE_HOME", os.path.join(HERE, "cosyvoice"))


def cosy_available():
    return os.path.exists(os.path.join(COSY_DIR, "venv", "bin", "python")) and os.path.isdir(os.path.join(COSY_DIR, "CosyVoice"))


def _cosy_lines(lines, v):
    c = v.get("cosyvoice") or {}
    with tempfile.TemporaryDirectory() as d:
        job = {"lines": lines, "out": d, "model": c.get("model", "CosyVoice-300M-SFT"), "speaker": c.get("speaker", "中文女"),
               "prompt_wav": c.get("prompt_wav", ""), "prompt_text": c.get("prompt_text", ""), "instruct": c.get("instruct", "")}
        jf = os.path.join(d, "job.json")
        json.dump(job, open(jf, "w"), ensure_ascii=False)
        subprocess.run([os.path.join(COSY_DIR, "venv", "bin", "python"), os.path.join(HERE, "cosy_worker.py"), jf], check=True,
                       env={**os.environ, "COSYVOICE_HOME": COSY_DIR})
        return [_to_sr(os.path.join(d, f"{i:03d}.wav")) for i in range(len(lines))]


# ───────── sherpa-onnx（kokoro / melo / baker） ─────────
def _sherpa_lines(lines, v):
    sys.path.insert(0, HERE)
    from tts2 import make
    c = v.get("sherpa") or {}
    tts = make(c.get("kind", "kokoro"))
    out = []
    for t in lines:
        a = tts.generate(t, sid=int(c.get("speaker", 3)), speed=float(c.get("speed", 1.0)))
        x = np.array(a.samples, dtype=np.float32)
        if a.sample_rate != SR:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                sf.write(f.name, x, a.sample_rate)
            x = _to_sr(f.name)
            os.remove(f.name)
        out.append(x)
    return out


def pick(v):
    p = v.get("provider", "auto")
    if p != "auto":
        return p
    if volc_available(v):
        return "volcengine"
    if cosy_available():
        return "cosyvoice"
    return "sherpa"


def synth(lines, voice, target=90, min_speed=1.0, max_speed=1.5):
    lines = [t.replace("：", "，") for t in lines]
    provider = pick(voice)
    fn = {"volcengine": _volc_lines, "cosyvoice": _cosy_lines, "sherpa": _sherpa_lines}[provider]
    try:
        segs = fn(lines, voice)
    except Exception as e:
        if provider == "sherpa" or voice.get("provider") not in ("auto", None):
            raise
        print(f"配音：{provider} 失败（{e}），退回 sherpa", file=sys.stderr)
        provider, segs = "sherpa", _sherpa_lines(lines, voice)
    total = sum(len(s) for s in segs) / SR + GAP * (len(lines) - 1)
    speed = max(min_speed, min(max_speed, total / (target - 0.6)))
    if abs(speed - 1.0) >= 0.01:
        segs = [_atempo(s, speed) for s in segs]
    out, times, t = [np.zeros(int(0.3 * SR), np.float32)], [], 0.3
    for s in segs:
        times.append((t, t + len(s) / SR))
        out.append(s)
        t += len(s) / SR
        out.append(np.zeros(int(GAP * SR), np.float32))
        t += GAP
    audio = np.concatenate(out)
    audio = audio / (np.abs(audio).max() + 1e-6) * 0.9
    print(f"配音：{provider}，语速 x{speed:.2f}", file=sys.stderr)
    return audio, SR, times, speed
