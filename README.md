# Shahnameh Film Studio

An AI film studio for the Shahnameh: design characters, write a scene-by-scene script, generate keyframes, animate them with **LTX-2.5**, dub the dialogue with cloned voices, and export a final cut with subtitles.

The studio is provider-agnostic. Every API (image, video, speech, LLM) is configured **inside the UI** (Settings tab), so it can run on a local GPU box, a cloud API, or a mix.

## Features

- **Characters** — text-to-image portraits, reference-guided edits ("same face, add a beard"), wardrobe variants, canonical image, voice profile with cloning.
- **Script** — a treatment becomes a structured scene list with an LLM (DeepSeek / any OpenAI-compatible chat API); every scene and line is editable.
- **Scenes** — cast characters per scene, compile a cinematic English prompt, generate a look frame with character references, then animate it.
- **Continuity** — take the last frame of the previous scene and use it as the first frame of the next one.
- **Renders** — queue video jobs, watch status, preview, cancel. OpenAI Videos (Sora-style) contract.
- **Dubbing & subtitles** — each scene's dialogue is synthesized with its character's voice; the final cut mixes it over the video and exports an SRT.
- **Settings** — swap image/video/TTS/LLM providers at runtime, with a connection test per provider.

## Architecture

```
frontend (React + Vite)  ──HTTP──▶  backend (FastAPI + SQLite)
                                        │
                                        ├─ image  → Flux gateway / OpenAI Images
                                        ├─ video  → LTX-2.5 gateway (OpenAI Videos)
                                        ├─ speech → Piper / Fish Speech / OpenAI TTS
                                        └─ llm    → OpenAI-compatible chat
```

`gateway/ltx_video_api.py` is a small OpenAI-Videos-compatible API that wraps ComfyUI running LTX-2.5 (two-stage distilled pipeline, audio+video, first/last frame guidance, VRAM guard). ComfyUI stays an implementation detail.

## Quick start

```bash
# backend
cd backend
cp .env.example .env          # edit paths, provider URLs and keys
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099

# frontend (dev)
cd frontend
npm install
npm run dev                    # proxies /api to :8099

# or build once and let FastAPI serve it at /
npm run build
```

Open `http://localhost:8099`.

### Minimal `.env`

```ini
STUDIO_DATA=/path/to/studio/data
IMAGE_PROVIDER=flux_gateway
FLUX_API_BASE=http://gpu-host:8090
VIDEO_API_BASE=http://gpu-host:8091
TTS_PROVIDER=piper
LLM_BASE=https://api.avalai.ir/v1
LLM_MODEL=deepseek-v4.1-flash
AVALAI_KEY=...
FFMPEG_BIN=/path/to/studio/bin/ffmpeg
```

`TTS_PROVIDER=fish` points at a Fish Speech server (`/v1/tts` + `/v1/references/add` for cloning).

## Video gateway

```bash
cd gateway
COMFY_URL=http://127.0.0.1:8188 PORT=8091 python3 ltx_video_api.py
```

- `POST /v1/videos` — `{prompt, size, seconds, fps, seed, audio, first_frame?, last_frame?}`
- `GET /v1/videos/{id}` — status
- `GET /v1/videos/{id}/content` — mp4
- `POST /v1/videos/{id}/cancel`
- `GET /v1/health`

## Notes

- Model weights, generated media and API keys are **not** part of this repository.
- External models (LTX-2.5, Fish Speech, Flux) keep their own licenses; use them accordingly.
