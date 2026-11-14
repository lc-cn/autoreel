"""自影 · 配音清晰度检查：把合成的语音用离线语音识别转回文字，和原稿按拼音逐字比对。

- 比的是不带声调的拼音，同音字（识别成「在/再」）不算错，只抓吞字、漏字、多字、念错音。
- 识别模型：sherpa-onnx Paraformer 中文小模型（约 80MB，setup.sh 下载到 tools/models/）。
- 没有模型或没装 pypinyin 时返回 None，配音照常进行，只是不做检查。

用法：
    qc = Checker()                       # 加载一次
    r = qc.check(audio_float32_24k, "原稿")  # -> {"cer": 0.04, "heard": "识别结果", "diff": "…"} 或 None
"""
import os
import re

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "sherpa-onnx-paraformer-zh-small-2024-03-09")
_CN = re.compile(r"[一-鿿]")


def plain(text):
    """去掉配音标记，只留下会被念出来的字：{行|háng} → 行，[breath]、<strong> 去掉。"""
    text = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", text)
    text = re.sub(r"\[[a-z_\-]+\]|</?strong>|</?laughter>", "", text)
    return text


def _syllables(text):
    from pypinyin import lazy_pinyin
    chars = _CN.findall(plain(text))
    return chars, lazy_pinyin("".join(chars))


def _edit_ops(a, b):
    """Levenshtein，返回 (距离, 对齐后 a 中出错位置的集合)。"""
    n, m = len(a), len(b)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (a[i - 1] != b[j - 1]))
    bad, i, j = set(), n, m
    while i > 0 and j > 0:
        if d[i, j] == d[i - 1, j - 1] + (a[i - 1] != b[j - 1]):
            if a[i - 1] != b[j - 1]:
                bad.add(i - 1)
            i, j = i - 1, j - 1
        elif d[i, j] == d[i - 1, j] + 1:
            bad.add(i - 1); i -= 1
        else:
            j -= 1
    bad.update(range(i))
    return int(d[n, m]), bad


class Checker:
    def __init__(self):
        import sherpa_onnx
        import pypinyin  # noqa: F401  确认可用
        self.rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
            paraformer=os.path.join(MODEL, "model.int8.onnx"), tokens=os.path.join(MODEL, "tokens.txt"),
            num_threads=max(1, (os.cpu_count() or 2) // 2), sample_rate=16000, feature_dim=80, decoding_method="greedy_search")

    def heard(self, audio, sr=24000):
        if sr != 16000:  # 简单线性重采样，识别够用
            x = np.interp(np.arange(0, len(audio), sr / 16000), np.arange(len(audio)), audio).astype(np.float32)
        else:
            x = audio.astype(np.float32)
        if len(x) < 16000 * 0.3:  # 太短（几乎是空白）识别模型会报错，直接当作没听到
            return ""
        s = self.rec.create_stream()
        s.accept_waveform(16000, x)
        self.rec.decode_stream(s)
        return s.result.text

    def check(self, audio, text, sr=24000):
        chars, want = _syllables(text)
        if not want:
            return {"cer": 0.0, "heard": "", "diff": ""}
        got_text = self.heard(audio, sr)
        _, got = _syllables(got_text)
        dist, bad = _edit_ops(want, got)
        diff = "".join(f"〔{c}〕" if k in bad else c for k, c in enumerate(chars))
        return {"cer": round(dist / len(want), 3), "heard": got_text, "diff": diff}


def load():
    """能用就返回 Checker，否则返回 None（不影响出片）。"""
    if not os.path.exists(os.path.join(MODEL, "model.int8.onnx")):
        return None
    try:
        return Checker()
    except Exception:
        return None
