"""在 CosyVoice 的 Python 3.10 环境里运行：读入任务 JSON，逐句合成 wav。由 tts.py 调用，一般不需要手动运行。

任务格式：
  {"model": "Fun-CosyVoice3-0.5B" | "CosyVoice2-0.5B" | "CosyVoice-300M-SFT",
   "out": "输出目录",
   "lines": [{"text": "…", "prompt_wav": "参考录音", "prompt_text": "录音里说的话",
              "instruct": "请非常开心地说一句话。", "speaker": "中文女", "speed": 1.0, "seed": 0}, …]}
  每句输出 out/000.wav、001.wav……
  - 有 prompt_wav：按参考录音的音色和语气合成（zero-shot）；再给 instruct 就按指令调整（instruct2）。
  - 没有 prompt_wav：用 SFT 内置音色（只有 CosyVoice-300M-SFT 支持）。
  - 只能使用你有权使用的声音做参考录音。
"""
import json
import os
import sys

HOME = os.environ.get("COSYVOICE_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cosyvoice"))
sys.path.insert(0, os.path.join(HOME, "CosyVoice"))
sys.path.insert(0, os.path.join(HOME, "CosyVoice", "third_party", "Matcha-TTS"))

import torch  # noqa: E402
import torchaudio  # noqa: E402

torch.set_num_threads(max(1, os.cpu_count() or 1))
job = json.load(open(sys.argv[1], encoding="utf-8"))
name = job.get("model", "Fun-CosyVoice3-0.5B")
model_dir = name if os.path.isabs(name) else os.path.join(HOME, "pretrained_models", name)

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402
from cosyvoice.utils.common import set_all_random_seed  # noqa: E402

m = AutoModel(model_dir=model_dir)
V3 = type(m).__name__ == "CosyVoice3"
SYS = "You are a helpful assistant."

lines = job["lines"]
for i, ln in enumerate(lines):
    if isinstance(ln, str):  # 旧格式：lines 是字符串，其余字段在 job 顶层
        ln = {"text": ln, **{k: job.get(k) for k in ("speaker", "prompt_wav", "prompt_text", "instruct") if job.get(k)}}
    text, speed = ln["text"], float(ln.get("speed", 1.0))
    set_all_random_seed(int(ln.get("seed", 0)))
    pw, ins = ln.get("prompt_wav"), (ln.get("instruct") or "").strip()
    if pw and ins:
        ins = f"{SYS} {ins}<|endofprompt|>" if V3 and "<|endofprompt|>" not in ins else ins
        gen = m.inference_instruct2(text, ins, pw, stream=False, speed=speed)
    elif pw:
        pt = ln.get("prompt_text", "")
        pt = f"{SYS}<|endofprompt|>{pt}" if V3 and "<|endofprompt|>" not in pt else pt
        gen = m.inference_zero_shot(text, pt, pw, stream=False, speed=speed)
    else:
        gen = m.inference_sft(text, ln.get("speaker", "中文女"), stream=False, speed=speed)
    wav = torch.cat([g["tts_speech"] for g in gen], dim=1)
    torchaudio.save(os.path.join(job["out"], f"{i:03d}.wav"), wav, m.sample_rate)
    print(f"cosyvoice {i + 1}/{len(lines)}", file=sys.stderr, flush=True)
