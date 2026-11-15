"""自影 · 混音：配音 + 背景音乐（人声出现时自动压低）+ 音效（转场「嗖」、关键词「叮」、结尾提示音）。

音效用 HyperFrames 自带的音效库（来自 Pixabay，可免费商用、无需署名，setup.sh 装 hyperframes 时一起装好）。
背景音乐：频道 channel.json 的 voice.bgm
  "auto"（默认）按频道默认语气合成一段柔和的背景乐（tools/bgm.py，没有版权问题）
  "none" 不要背景音乐
  "xxx.mp3" 用仓库 assets/music/ 里你自己放的音乐（比如从 Pixabay 音乐下载的）

    mix(voice, sr, events, bgm, root) -> 混好的 float32 数组
    events = [(秒, "whoosh-short" | "pop" | "chime" | ...), ...]
"""
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
SFX_DIR = os.path.join(HERE, "node_modules", "hyperframes", "dist", "skills", "media-use", "audio", "assets", "sfx")
SFX_GAIN = {"whoosh-short": 0.30, "whoosh": 0.28, "pop": 0.22, "click-soft": 0.25, "chime": 0.28, "riser": 0.22, "sparkle": 0.22, "ping": 0.2}


def _load(path, sr):
    with tempfile.TemporaryDirectory() as d:
        out = f"{d}/a.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "1", "-ar", str(sr), out], check=True)
        a, _ = sf.read(out, dtype="float32")
    return a


_CACHE = {}


def sfx(name, sr):
    key = (name, sr)
    if key not in _CACHE:
        p = os.path.join(SFX_DIR, f"{name}.mp3")
        _CACHE[key] = _load(p, sr) if os.path.exists(p) else None
    return _CACHE[key]


def _envelope(v, sr, attack=0.05, release=0.35):
    """人声包络（0–1），用来给背景音乐让路。"""
    hop = int(sr * 0.01)
    rms = np.sqrt(np.convolve(v ** 2, np.ones(hop * 3) / (hop * 3), "same"))[::hop]
    act = np.clip(rms / (rms.max() * 0.12 + 1e-6), 0, 1)
    out = np.zeros_like(act)
    a, r, acc = np.exp(-0.01 / attack), np.exp(-0.01 / release), 0.0
    for i, x in enumerate(act):
        acc = a * acc + (1 - a) * x if x > acc else r * acc + (1 - r) * x
        out[i] = acc
    return np.repeat(out, hop)[: len(v)] if len(out) * hop >= len(v) else np.pad(np.repeat(out, hop), (0, len(v) - len(out) * hop), "edge")


def background(bgm, mood, seconds, sr, root):
    """返回背景音乐数组；bgm 为 none 或出错时返回 None。"""
    if not bgm or bgm == "none":
        return None
    try:
        if bgm != "auto":
            p = bgm if os.path.isabs(bgm) else os.path.join(root, "assets", "music", bgm)
            a = _load(p, sr)
            n = int(seconds * sr)
            a = np.tile(a, n // max(1, len(a)) + 1)[:n]
            f = min(n, int(1.5 * sr))
            a[-f:] *= np.linspace(1, 0, f)
            return a / (np.abs(a).max() + 1e-6) * 0.5
        import bgm as B
        return B.make(mood, seconds, sr)
    except Exception as e:  # 背景音乐出问题不影响出片
        print(f"提醒：背景音乐没加上（{e}）")
        return None


def mix(voice, sr, events, bgm=None, quiet=0.16, under=0.055):
    """voice：配音；bgm：同采样率的背景音乐（可为 None）；quiet / under：没人声 / 有人声时背景音乐的音量。"""
    n = len(voice)
    out = voice.astype(np.float32).copy()
    if bgm is not None:
        b = np.pad(bgm, (0, max(0, n - len(bgm))))[:n]
        env = _envelope(voice, sr)
        out += b * (quiet - (quiet - under) * env)
    for t, name in events:
        s = sfx(name, sr)
        if s is None:
            continue
        st = int(max(0, t) * sr)
        if st >= n:
            continue
        seg = s[: n - st] * SFX_GAIN.get(name, 0.22)
        out[st:st + len(seg)] += seg
    peak = np.abs(out).max()
    return out / peak * 0.95 if peak > 0.95 else out
