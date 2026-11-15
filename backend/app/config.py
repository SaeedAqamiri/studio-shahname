from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")
_load_env(ROOT / ".env.local")

DATA = Path(os.environ.get("STUDIO_DATA", str(ROOT / "data")))
ASSETS = DATA / "assets"
DB_PATH = DATA / "studio.db"
for d in (DATA, ASSETS):
    d.mkdir(parents=True, exist_ok=True)

IMAGE_PROVIDER = os.environ.get("IMAGE_PROVIDER", "flux_gateway")
FLUX_API_BASE = os.environ.get("FLUX_API_BASE", "http://172.16.20.117:8090").rstrip("/")
OPENAI_IMAGE_BASE = os.environ.get("OPENAI_IMAGE_BASE", "https://api.avalai.ir/v1").rstrip("/")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "cf.flux-2-klein-9b")

VIDEO_PROVIDER = os.environ.get("VIDEO_PROVIDER", "ltx_openai")
VIDEO_API_BASE = os.environ.get("VIDEO_API_BASE", "http://172.16.20.117:8091").rstrip("/")

TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "piper")
TTS_MODEL = os.environ.get("TTS_MODEL", "gpt-audio-1.5")
PIPER_VOICE = os.environ.get("PIPER_VOICE", "fa_IR-amir-medium")

AVALAI_KEY = os.environ.get("AVALAI_KEY", "")
LLM_BASE = os.environ.get("LLM_BASE", "https://api.avalai.ir/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4.1-flash")

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", str(ROOT.parent / "bin" / "ffmpeg"))

STYLE_DEFAULT = {
    "art_direction": "cinematic film still, Persian epic, Shahnameh, grounded historical fantasy",
    "palette": "warm gold, deep teal, terracotta, charcoal",
    "lighting": "dramatic volumetric light, soft rim light",
    "lens": "35mm anamorphic, shallow depth of field",
    "negative": "cartoon, anime, low quality, deformed, extra limbs, text, watermark, modern objects",
}
