#!/bin/bash
# 自影：安装依赖、配音引擎和 HyperFrames 渲染器。重复运行会跳过已装好的部分。
# 安装哪种配音由 autoreel.config.json 的 voice.provider 决定：
#   volcengine → 不用下载大模型；cosyvoice / auto → 安装 Fun-CosyVoice3（约 4GB，首次 5–15 分钟）；sherpa → 下载轻量模型
set -e
cd "$(dirname "$0")"
python3 -m pip install -q sherpa-onnx soundfile numpy pillow fonttools brotli rjieba pypinyin 2>&1 | grep -v WARN || true
python3 -m pip install -q --ignore-installed pillow 2>&1 | grep -v WARN || true  # 新环境自带的 Pillow 可能损坏
cfg() { python3 -c "import json,os;p='../autoreel.config.json';c=json.load(open(p)) if os.path.exists(p) else {};v=c.get('voice',{});print($1)"; }
PROVIDER=$(cfg "v.get('provider','auto')")
APPID=$(cfg "v.get('volcengine',{}).get('app_id','')")
COSY_MODEL=$(cfg "v.get('cosyvoice',{}).get('model','Fun-CosyVoice3-0.5B')")
SHERPA_KIND=$(cfg "v.get('sherpa',{}).get('kind','kokoro')")
if [ "$PROVIDER" = auto ]; then [ -n "$APPID" ] && PROVIDER=volcengine || PROVIDER=cosyvoice; fi
command -v ffmpeg >/dev/null || { apt-get install -y -q ffmpeg >/dev/null 2>&1 || sudo apt-get install -y -q ffmpeg >/dev/null 2>&1 || true; }

install_sherpa() {
  mkdir -p models
  local R=https://github.com/k2-fsa/sherpa-onnx/releases/download
  get() { [ -e "models/$1" ] || { curl -sSL --retry 3 -o models/t.tar.bz2 "$R/tts-models/$1.tar.bz2" && tar xjf models/t.tar.bz2 -C models && rm models/t.tar.bz2; }; }
  case "$SHERPA_KIND" in
    baker) get matcha-icefall-zh-baker
           [ -f models/vocos-22khz-univ.onnx ] || curl -sSL --retry 3 -o models/vocos-22khz-univ.onnx $R/vocoder-models/vocos-22khz-univ.onnx ;;
    melo)  get vits-melo-tts-zh_en ;;
    *)     get kokoro-multi-lang-v1_1 ;;
  esac
}

install_cosyvoice() {
  # CosyVoice 需要 Python 3.10，装在独立环境里，不影响系统 Python
  local H=cosyvoice
  mkdir -p $H
  command -v uv >/dev/null || python3 -m pip install -q uv
  [ -d $H/CosyVoice ] || git clone -q --depth 1 --recursive https://github.com/FunAudioLLM/CosyVoice.git $H/CosyVoice
  if ! $H/venv/bin/python -c "import torch, whisper, wetext, pyworld" 2>/dev/null; then
    uv venv -q --python 3.10 $H/venv
    VIRTUAL_ENV=$H/venv uv pip install -q torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu
    VIRTUAL_ENV=$H/venv uv pip install -q "setuptools<70" wheel
    VIRTUAL_ENV=$H/venv uv pip install -q --no-build-isolation openai-whisper==20231117
    VIRTUAL_ENV=$H/venv uv pip install -q conformer==0.3.2 diffusers==0.29.0 hydra-core==1.3.2 HyperPyYAML==1.2.3 inflect==7.3.1 \
      librosa==0.10.2 lightning==2.2.4 modelscope==1.20.0 omegaconf==2.3.0 onnx==1.16.0 onnxruntime==1.18.0 transformers==4.51.3 \
      x-transformers==2.11.24 wetext==0.0.4 soundfile numpy==1.26.4 matplotlib pyarrow rich==13.7.1 gdown==5.1.0 wget==3.2 \
      networkx==3.1 pydantic==2.7.0 "protobuf==4.25" pyworld==0.3.4 huggingface_hub
  fi
  if ! ls $H/pretrained_models/$COSY_MODEL/cosyvoice*.yaml >/dev/null 2>&1; then
    # 优先 HuggingFace（快，只下 CPU 需要的文件），失败再用魔搭 ModelScope
    $H/venv/bin/python - "$COSY_MODEL" "$H/pretrained_models/$COSY_MODEL" <<'PY'
import os, sys
m, out = sys.argv[1], sys.argv[2]
repo = {"Fun-CosyVoice3-0.5B": "Fun-CosyVoice3-0.5B-2512"}.get(m, m)
pats = ["*.yaml", "*.json", "flow.pt", "hift.pt", "campplus.onnx", "speech_tokenizer_v*.onnx", "CosyVoice-BlankEN/*"]
pats += ["llm.rl.pt"] if m.startswith("Fun-CosyVoice3") else ["llm.pt", "spk2info.pt"]  # CosyVoice3 用字错率更低的 RL 版
try:
    from huggingface_hub import snapshot_download
    snapshot_download(f"FunAudioLLM/{repo}", local_dir=out, allow_patterns=pats, ignore_patterns=["*.batch.onnx"])
except Exception as e:
    print("HuggingFace 下载失败，改用 ModelScope：", e)
    from modelscope import snapshot_download
    snapshot_download(f"FunAudioLLM/{repo}" if m.startswith("Fun-") else f"iic/{m}", local_dir=out)
if os.path.exists(f"{out}/llm.rl.pt"):
    os.replace(f"{out}/llm.rl.pt", f"{out}/llm.pt")
PY
  fi
  $H/venv/bin/python -c "import torch, whisper, wetext, pyworld; print('CosyVoice 环境 OK')"
}

case "$PROVIDER" in
  volcengine) echo "配音：火山引擎（无需下载大模型，另装轻量模型作兜底）"; install_sherpa ;;
  cosyvoice)  install_cosyvoice || { echo "CosyVoice 安装失败，改用 sherpa 兜底"; install_sherpa; } ;;
  *)          install_sherpa ;;
esac

# 配音清晰度检查用的离线识别模型（约 80MB）
ASR=sherpa-onnx-paraformer-zh-small-2024-03-09
[ -f models/$ASR/model.int8.onnx ] || { mkdir -p models && curl -sSL --retry 3 -o models/asr.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$ASR.tar.bz2 && tar xjf models/asr.tar.bz2 -C models && rm models/asr.tar.bz2; } || echo "识别模型下载失败，跳过配音清晰度检查"
[ -f package.json ] || npm init -y >/dev/null
[ -d node_modules/hyperframes ] || npm install -s hyperframes@0.9.37 gsap@3.15.0
[ -d node_modules/world-atlas ] || npm install -s d3-geo@3.1.1 topojson-client@3.1.0 world-atlas@2.0.2
command -v ffmpeg >/dev/null || { apt-get install -y -q ffmpeg >/dev/null 2>&1 || sudo apt-get install -y -q ffmpeg >/dev/null 2>&1 || true; }
[ -f /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc ] || { apt-get install -y -q fonts-wqy-zenhei >/dev/null 2>&1 || sudo apt-get install -y -q fonts-wqy-zenhei >/dev/null 2>&1 || true; }
python3 -c "import sherpa_onnx, soundfile, fontTools, rjieba; from PIL import Image, ImageDraw; print('python 依赖 OK')"
echo "配音引擎：$PROVIDER"
if [ -n "$PEXELS_API_KEY$PIXABAY_API_KEY" ]; then echo "实拍素材：已配置"; else echo "实拍素材：未配置 PEXELS_API_KEY / PIXABAY_API_KEY，footage 分镜会退回文字画面"; fi
HYPERFRAMES_NO_TELEMETRY=1 npx hyperframes --version
