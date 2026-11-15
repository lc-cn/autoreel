"""自影 · 背景音乐：按语气合成一段柔和的循环背景乐（没有版权问题），或者用你放在 assets/music/ 里的音乐。

合成的音乐只做「铺底」：和弦铺垫 + 轻拨弦琶音 + 低音 + 轻鼓点，音量很低，有人声时会被压得更低。
想要更好听的：从 Pixabay 音乐（https://pixabay.com/music/ ，可免费商用）下载 mp3 放进仓库 assets/music/，
在频道 channel.json 的 voice.bgm 填文件名（或插件「频道」页里选）。

    make(mood, seconds, sr=24000) -> np.ndarray（float32，单声道，峰值约 0.5）
"""
import numpy as np

# 每种语气：调式（以 MIDI 音高表示的 4 个和弦）、速度、是否有鼓点、琶音密度
NOTE = {"C": 60, "D": 62, "E": 64, "F": 65, "G": 67, "A": 69, "B": 71}
MAJ, MIN = (0, 4, 7), (0, 3, 7)


def _chord(root, kind, octave=0):
    r = NOTE[root[0]] + (1 if "#" in root else -1 if root.endswith("b") else 0) + 12 * octave
    return [r + x for x in (MAJ if kind == "M" else MIN)]


PRESETS = {
    "轻快": dict(bpm=112, chords=[("C", "M"), ("G", "M"), ("A", "m"), ("F", "M")], drums=True, arp=2),
    "激昂": dict(bpm=120, chords=[("A", "m"), ("F", "M"), ("C", "M"), ("G", "M")], drums=True, arp=2),
    "平稳": dict(bpm=100, chords=[("D", "m"), ("Bb", "M"), ("F", "M"), ("C", "M")], drums=True, arp=1),
    "严肃": dict(bpm=88, chords=[("E", "m"), ("C", "M"), ("G", "M"), ("D", "M")], drums=False, arp=1),
    "温暖": dict(bpm=86, chords=[("F", "M"), ("C", "M"), ("D", "m"), ("Bb", "M")], drums=False, arp=1),
    "沉重": dict(bpm=72, chords=[("A", "m"), ("F", "M"), ("D", "m"), ("E", "m")], drums=False, arp=0),
    "惊讶": dict(bpm=104, chords=[("G", "M"), ("E", "m"), ("C", "M"), ("D", "M")], drums=True, arp=2),
    "悬念": dict(bpm=76, chords=[("A", "m"), ("A", "m"), ("F", "M"), ("E", "m")], drums=False, arp=1),
}


def _hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n, sr, a=0.01, r=0.3):
    t = np.arange(n) / sr
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))
    return e.astype(np.float32)


def _pad(freqs, n, sr):
    t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    for f in freqs:
        for k, amp in ((1, 1.0), (2, 0.35), (3, 0.15)):
            for det in (-0.6, 0.6):  # 轻微失谐，让声音更厚
                out += amp * np.sin(2 * np.pi * (f * k + det) * t + k).astype(np.float32)
    a = min(n, int(0.4 * sr))
    env = np.ones(n, np.float32)
    env[:a] = np.linspace(0, 1, a)
    env[-a:] = np.linspace(1, 0, a)
    return out * env / (len(freqs) * 3)


def _pluck(f, n, sr, seed):
    """Karplus-Strong 拨弦。"""
    rng = np.random.default_rng(seed)
    p = max(2, int(sr / f))
    buf = rng.uniform(-1, 1, p).astype(np.float32)
    out = np.zeros(n, np.float32)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = 0.5 * (buf[i % p] + buf[(i + 1) % p]) * 0.994
    return out


def _kick(sr):
    n = int(0.25 * sr)
    t = np.arange(n) / sr
    f = 110 * np.exp(-t * 18) + 45
    return (np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 14)).astype(np.float32)


def _hat(sr, seed):
    n = int(0.05 * sr)
    x = np.random.default_rng(seed).uniform(-1, 1, n).astype(np.float32)
    x = np.diff(x, prepend=0)  # 简单高通
    return x * np.exp(-np.arange(n) / sr * 70).astype(np.float32)


def _lowpass(x, sr, fc):
    a = np.exp(-2 * np.pi * fc / sr)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def make(mood="平稳", seconds=50.0, sr=24000, seed=7):
    P = PRESETS.get(mood, PRESETS["平稳"])
    beat = 60.0 / P["bpm"]
    bar = int(4 * beat * sr)
    phrase = [_chord(r, k) for r, k in P["chords"]]
    loop = np.zeros(bar * 4, np.float32)
    kick, hat = _kick(sr), _hat(sr, seed)
    for b, ch in enumerate(phrase):
        s = b * bar
        loop[s:s + bar] += 0.55 * _pad([_hz(m) for m in ch], bar, sr)
        bass = _hz(ch[0] - 24)
        t = np.arange(bar) / sr
        loop[s:s + bar] += 0.35 * np.sin(2 * np.pi * bass * t).astype(np.float32) * _env(bar, sr, 0.02, 1.6)
        steps = {0: 0, 1: 4, 2: 8}[P["arp"]]
        for k in range(steps):
            m = ch[k % 3] + 12 * (1 + (k // 3) % 2)
            st = s + int(k * bar / steps)
            n = int(bar / steps)
            loop[st:st + n] += 0.18 * _pluck(_hz(m), n, sr, seed + b * 10 + k) * _env(n, sr, 0.002, 0.35)
        if P["drums"]:
            for q in range(4):
                st = s + int(q * beat * sr)
                if q in (0, 2):
                    loop[st:st + len(kick)] += 0.45 * kick[: max(0, min(len(kick), len(loop) - st))]
                hs = st + int(beat * sr / 2)
                if hs + len(hat) <= len(loop):
                    loop[hs:hs + len(hat)] += 0.12 * hat
    loop = _lowpass(loop, sr, 5200)
    n = int(seconds * sr)
    out = np.tile(loop, n // len(loop) + 1)[:n]
    f = min(n, int(1.5 * sr))
    out[:f] *= np.linspace(0, 1, f)
    out[-f:] *= np.linspace(1, 0, f)
    return (out / (np.abs(out).max() + 1e-6) * 0.5).astype(np.float32)


if __name__ == "__main__":
    import sys
    import soundfile as sf
    mood = sys.argv[1] if len(sys.argv) > 1 else "平稳"
    sf.write(sys.argv[2] if len(sys.argv) > 2 else f"/tmp/bgm-{mood}.wav", make(mood, 20), 24000)
