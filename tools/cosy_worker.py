"""在 CosyVoice 的 Python 3.10 环境里运行：读入任务 JSON，逐行合成 wav。
由 tts.py 调用，一般不需要手动运行。
任务字段：lines、out、model（CosyVoice-300M-SFT / CosyVoice2-0.5B）、speaker（SFT 内置音色，如「中文女」「中文男」）、
prompt_wav + prompt_text（用一段参考录音复刻音色，仅限你有权使用的声音，比如你自己的录音）、instruct（可选，风格描述）。
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
model_dir = os.path.join(HOME, "pretrained_models", job["model"])

if job["model"].startswith("CosyVoice2"):
    from cosyvoice.cli.cosyvoice import CosyVoice2
    from cosyvoice.utils.file_utils import load_wav
    m = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=False)
    prompt = load_wav(job["prompt_wav"], 16000) if job.get("prompt_wav") else None
else:
    from cosyvoice.cli.cosyvoice import CosyVoice
    m = CosyVoice(model_dir, load_jit=False, load_trt=False, fp16=False)
    prompt = None

for i, text in enumerate(job["lines"]):
    if prompt is not None and job.get("instruct"):
        gen = m.inference_instruct2(text, job["instruct"], prompt, stream=False)
    elif prompt is not None:
        gen = m.inference_zero_shot(text, job.get("prompt_text", ""), prompt, stream=False)
    else:
        gen = m.inference_sft(text, job.get("speaker", "中文女"), stream=False)
    wav = torch.cat([g["tts_speech"] for g in gen], dim=1)
    torchaudio.save(os.path.join(job["out"], f"{i:03d}.wav"), wav, m.sample_rate)
    print(f"cosyvoice {i + 1}/{len(job['lines'])}", file=sys.stderr, flush=True)
