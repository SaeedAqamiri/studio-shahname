# Deploying Fish Speech S2-Pro (4B) for Persian TTS + cloning

This is how the studio's `fish` TTS provider was set up on the GPU box (H100, Ubuntu 22.04, CUDA 13).

## 1. Weights

```bash
hf download fishaudio/s2-pro --local-dir ~/fish/s2-pro
# needs: model-0000{1,2}-of-00002.safetensors, codec.pth, config.json, tokenizer*
```

License: Fish Audio Research License (non-commercial use).

## 2. Code + Python environment

```bash
git clone --depth 1 https://github.com/fishaudio/fish-speech ~/fish/repo
python3 -m venv ~/fish/venv
~/fish/venv/bin/pip install kui baize pyrootutils ormsgpack
~/fish/venv/bin/pip install --no-deps descript-audiotools descript-audio-codec \
    argbind julius flatten-dict natsort cachetools opencc-python-reimplemented importlib_resources
```

Reuse the GPU box's existing torch/transformers (the studio box used the ComfyUI venv):

```
PYTHONPATH=~/fish/venv/lib/python3.10/site-packages:~/fish/repo \
  ~/flux3-klein/venv-comfy/bin/python tools/api_server.py ...
```

## 3. Two small patches

`audiotools/ml/__init__.py` — drop the heavy `Experiment` import so the codec can load without gradio:

```python
from . import decorators
from . import layers
from .accelerator import Accelerator
from .layers import BaseModel
```

`fish_speech/inference_engine/reference_loader.py` — fall back to soundfile when torchaudio/torchcodec cannot decode (no shared FFmpeg libs):

```python
try:
    waveform, original_sr = torchaudio.load(reference_audio, backend=self.backend)
except Exception:
    import soundfile as sf
    data, original_sr = sf.read(reference_audio, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(data.T.astype("float32"))
```

## 4. Start

```bash
cd ~/fish/repo
SP=$HOME/fish/venv/lib/python3.10/site-packages
PYTHONPATH=$SP:$PWD ~/flux3-klein/venv-comfy/bin/python tools/api_server.py \
  --listen 0.0.0.0:8094 \
  --llama-checkpoint-path ~/fish/s2-pro \
  --decoder-checkpoint-path ~/fish/s2-pro/codec.pth \
  --decoder-config-name modded_dac_vq \
  --device cuda --half
```

## 5. API used by the studio

```
POST /v1/tts                {text, reference_id?, format:"mp3"}
POST /v1/references/add     multipart: id, audio, text      # voice cloning
GET  /v1/references/list
GET  /v1/health
```

In the studio: **Settings → گفتار → provider: Fish Audio**, base URL `http://<gpu-host>:8094`.
Then in a character's voice panel upload 10–30 s of clean audio **with its exact transcript** and press «ساخت کلون صدا».
