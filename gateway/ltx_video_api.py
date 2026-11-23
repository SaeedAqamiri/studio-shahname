"""OpenAI-compatible video API for LTX-2.5 running inside ComfyUI.

The studio talks to this service only; ComfyUI is an implementation detail.
Endpoints follow the OpenAI Sora-style video API:

    POST   /v1/videos                     create a render job
    GET    /v1/videos                     list jobs
    GET    /v1/videos/{id}                job status
    GET    /v1/videos/{id}/content        download the mp4
    POST   /v1/videos/{id}/cancel         cancel
    DELETE /v1/videos/{id}                delete
    GET    /v1/health

Extra studio fields on POST: first_frame / last_frame (data URLs), negative,
seed, fps, audio, continuity ("first_frame" is enough), metadata.

The pipeline mirrors the official ComfyUI LTX-2.5 distilled templates:
two sampling stages (base at half resolution, then 2x latent upscale + refine),
with the audio latent carried through both stages.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_INPUT = Path(os.environ.get("COMFY_INPUT_DIR", "/home/ava/saeed/flux3-klein/comfy_input"))
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT_DIR", "/home/ava/saeed/flux3-klein/comfy_output"))
DATA_DIR = Path(os.environ.get("LTX_DATA_DIR", "/home/ava/studio/data"))
VIDEO_DIR = DATA_DIR / "videos"
DB_PATH = DATA_DIR / "videos.db"
API_TOKEN = os.environ.get("API_TOKEN", "")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8091"))
MIN_FREE_VRAM_MB = int(os.environ.get("MIN_FREE_VRAM_MB", "44000"))
JOB_TIMEOUT = float(os.environ.get("JOB_TIMEOUT", "2400"))

UNET = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
CLIP = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"

SIGMAS_BASE = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
SIGMAS_REFINE = "0.85, 0.7250, 0.4219, 0.0"
DEFAULT_NEGATIVE = (
    "blurry, low quality, watermark, text, deformed, extra limbs, "
    "jittery motion, flicker, cartoon, childish"
)

for d in (VIDEO_DIR, COMFY_INPUT):
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                model TEXT,
                prompt TEXT NOT NULL,
                negative TEXT,
                width INTEGER,
                height INTEGER,
                frames INTEGER,
                fps REAL,
                seconds REAL,
                seed INTEGER,
                audio INTEGER,
                mode TEXT,
                request_json TEXT,
                progress TEXT,
                comfy_prompt_id TEXT,
                output TEXT,
                error TEXT,
                created_at REAL,
                started_at REAL,
                finished_at REAL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at)")


def row_to_public(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "object": "video",
        "model": r["model"] or "ltx-2.5",
        "status": r["status"],
        "progress": r["progress"],
        "created_at": int(r["created_at"] or 0),
        "completed_at": int(r["finished_at"] or 0) or None,
        "seconds": r["seconds"],
        "size": f"{r['width']}x{r['height']}" if r["width"] else None,
        "fps": r["fps"],
        "seed": r["seed"],
        "audio": bool(r["audio"]),
        "mode": r["mode"],
        "error": r["error"],
        "content_url": f"/v1/videos/{r['id']}/content" if r["status"] == "succeeded" else None,
    }


# ---------------------------------------------------------------------------
# request model
# ---------------------------------------------------------------------------
class VideoRequest(BaseModel):
    model: str = "ltx-2.5"
    prompt: str = Field(min_length=1)
    negative: str | None = None
    size: str = Field(default="1280x720", pattern=r"^\d{3,4}x\d{3,4}$")
    seconds: float = Field(default=4.0, ge=1.0, le=20.0)
    fps: float = Field(default=24.0, ge=8.0, le=30.0)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    audio: bool = True
    first_frame: str | None = None  # data URL or absolute path
    last_frame: str | None = None  # data URL or absolute path
    metadata: dict[str, Any] = Field(default_factory=dict)


def require_token(x_api_key: str | None = Header(default=None)) -> None:
    if API_TOKEN and x_api_key != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api key")


# ---------------------------------------------------------------------------
# image staging
# ---------------------------------------------------------------------------
def _decode_image(value: str | None, tag: str) -> str | None:
    """Accept a data URL or a local path, return a filename inside COMFY_INPUT."""
    if not value:
        return None
    if value.startswith("data:"):
        header, _, payload = value.partition(",")
        raw = base64.b64decode(payload)
        ext = "png" if "png" in header else "jpg"
    else:
        p = Path(value)
        if not p.is_file():
            raise HTTPException(status_code=422, detail=f"{tag}: file not found")
        raw = p.read_bytes()
        ext = p.suffix.lstrip(".") or "png"
    name = f"studio_{tag}_{uuid.uuid4().hex[:12]}.{ext}"
    (COMFY_INPUT / name).write_bytes(raw)
    return name


# ---------------------------------------------------------------------------
# graph builders
# ---------------------------------------------------------------------------
def _common_nodes(prompt: str, negative: str, fps: float, width: int, height: int, frames: int, audio: bool):
    g: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "ltxv", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "5": {"class_type": "LTXVConditioning", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "frame_rate": fps}},
        "6": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": width // 2, "height": height // 2, "length": frames, "batch_size": 1}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
    }
    if audio:
        g["8"] = {"class_type": "LTXVEmptyLatentAudio", "inputs": {"frames_number": frames, "frame_rate": fps, "batch_size": 1, "audio_vae": ["7", 0]}}
        g["9"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["6", 0], "audio_latent": ["8", 0]}}
        start_latent = ["9", 0]
    else:
        start_latent = ["6", 0]
    return g, start_latent


def build_t2v(prompt: str, negative: str, width: int, height: int, frames: int, fps: float,
              seed: int, audio: bool, prefix: str) -> dict[str, Any]:
    g, start = _common_nodes(prompt, negative, fps, width, height, frames, audio)
    g.update({
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "12": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_BASE}},
        "13": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1], "video_cfg": 1.0, "audio_cfg": 1.0}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["10", 0], "guider": ["13", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": start}},
        "15": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["14", 0]}},
    })
    return _refine(g, audio, width, height, frames, fps, seed, prefix, image_node=None)


def build_i2v(prompt: str, negative: str, width: int, height: int, frames: int, fps: float,
              seed: int, audio: bool, prefix: str, first_frame: str | None = None,
              last_frame: str | None = None) -> dict[str, Any]:
    g, start = _common_nodes(prompt, negative, fps, width, height, frames, audio)

    guide = _decode_image(first_frame, "first")
    guide_last = _decode_image(last_frame, "last")
    if guide:
        g["40"] = {"class_type": "LoadImage", "inputs": {"image": guide}}
        g["41"] = {"class_type": "ImageScale", "inputs": {"image": ["40", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "center"}}
        g["42"] = {"class_type": "LTXVPreprocess", "inputs": {"image": ["41", 0], "img_compression": 18}}
        g["43"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["24", 0], "image": ["42", 0], "latent": ["6", 0], "strength": 0.7, "bypass": False}}
        start = ["43", 0]
        if audio:
            g["9"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["43", 0], "audio_latent": ["8", 0]}}
            start = ["9", 0]
    if guide_last:
        g["44"] = {"class_type": "LoadImage", "inputs": {"image": guide_last}}
        g["45"] = {"class_type": "ImageScale", "inputs": {"image": ["44", 0], "upscale_method": "lanczos", "width": width, "height": height, "crop": "center"}}
        g["46"] = {"class_type": "LTXVPreprocess", "inputs": {"image": ["45", 0], "img_compression": 18}}
        g["47"] = {"class_type": "LTXVAddGuide", "inputs": {
            "positive": ["5", 0], "negative": ["5", 1], "vae": ["24", 0],
            "latent": [start[0], 0], "image": ["46", 0], "frame_idx": frames - 1, "strength": 0.7,
        }}
        g["48"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": ["47", 1], "negative": ["47", 2], "latent": ["47", 0]}}
        g["5"] = {"class_type": "LTXVConditioning", "inputs": {"positive": ["48", 0], "negative": ["48", 1], "frame_rate": fps}}
        start = ["48", 2]

    g.update({
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral"}},
        "12": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_BASE}},
        "13": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1], "video_cfg": 1.0, "audio_cfg": 1.0}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["10", 0], "guider": ["13", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": start}},
        "15": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["14", 0]}},
    })
    return _refine(g, audio, width, height, frames, fps, seed, prefix, image_node=["42", 0] if guide else None)


def _refine(g: dict[str, Any], audio: bool, width: int, height: int, frames: int, fps: float,
            seed: int, prefix: str, image_node: list | None) -> dict[str, Any]:
    g["16"] = {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": UPSCALER}}
    g["17"] = {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": ["15", 0], "upscale_model": ["16", 0], "vae": ["24", 0]}}
    if image_node:
        g["50"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {"vae": ["24", 0], "image": image_node, "latent": ["17", 0], "strength": 1.0, "bypass": False}}
        base = ["50", 0]
    else:
        base = ["17", 0]
    if audio:
        g["18"] = {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": base, "audio_latent": ["15", 1]}}
        refine_in = ["18", 0]
    else:
        refine_in = base
    g.update({
        "19": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed + 1}},
        "20": {"class_type": "ManualSigmas", "inputs": {"sigmas": SIGMAS_REFINE}},
        "21": {"class_type": "LTXVDualCFGGuider", "inputs": {"model": ["1", 0], "positive": ["5", 0], "negative": ["5", 1], "video_cfg": 1.0, "audio_cfg": 1.0}},
        "22": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["19", 0], "guider": ["21", 0], "sampler": ["11", 0], "sigmas": ["20", 0], "latent_image": refine_in}},
        "23": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["22", 0]}},
        "25": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["23", 0], "vae": ["24", 0], "tile_size": 512, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}},
    })
    if audio:
        g["26"] = {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["23", 1], "audio_vae": ["7", 0]}}
        g["27"] = {"class_type": "CreateVideo", "inputs": {"images": ["25", 0], "fps": fps, "audio": ["26", 0]}}
    else:
        g["27"] = {"class_type": "CreateVideo", "inputs": {"images": ["25", 0], "fps": fps}}
    g["28"] = {"class_type": "SaveVideo", "inputs": {"video": ["27", 0], "filename_prefix": prefix, "format": "mp4"}}
    return g


# ---------------------------------------------------------------------------
# ComfyUI helpers
# ---------------------------------------------------------------------------
async def comfy_json(session: aiohttp.ClientSession, method: str, path: str, payload: dict | None = None) -> Any:
    async with session.request(method, COMFY_URL + path, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as r:
        text = await r.text()
        if r.status >= 400:
            raise RuntimeError(f"comfy {method} {path} -> {r.status}: {text[:800]}")
        return json.loads(text) if text else {}


async def ensure_vram(session: aiohttp.ClientSession) -> None:
    try:
        stats = await comfy_json(session, "GET", "/system_stats")
        free = min(d.get("vram_free", d.get("vram_total", 0)) for d in stats.get("devices", [])) / 1e6
        if free < MIN_FREE_VRAM_MB:
            await comfy_json(session, "POST", "/free", {"unload_models": True, "free_memory": True})
            await asyncio.sleep(2)
    except Exception:
        pass


def _find_output(outputs: dict[str, Any]) -> dict[str, str] | None:
    node = outputs.get("28") or {}
    for key in ("images", "videos", "gifs"):
        items = node.get(key)
        if items:
            return items[0]
    for value in outputs.values():
        for key in ("images", "videos", "gifs"):
            items = value.get(key)
            if items:
                return items[0]
    return None


async def run_job(session: aiohttp.ClientSession, job: dict[str, Any]) -> None:
    jid = job["id"]
    req = json.loads(job["request_json"])
    width = job["width"]
    height = job["height"]
    frames = job["frames"]
    fps = job["fps"]
    seed = job["seed"]
    audio = bool(job["audio"])
    prefix = f"studio/{jid}"
    mode = job["mode"]

    await ensure_vram(session)
    with db() as c:
        c.execute("UPDATE jobs SET status='running', started_at=?, progress='loading' WHERE id=?", (time.time(), jid))

    if mode == "i2v":
        graph = build_i2v(req["prompt"], job["negative"] or DEFAULT_NEGATIVE, width, height, frames, fps,
                          seed, audio, prefix, req.get("first_frame"), req.get("last_frame"))
    else:
        graph = build_t2v(req["prompt"], job["negative"] or DEFAULT_NEGATIVE, width, height, frames, fps,
                          seed, audio, prefix)

    res = await comfy_json(session, "POST", "/prompt", {"prompt": graph, "client_id": jid})
    pid = res.get("prompt_id")
    with db() as c:
        c.execute("UPDATE jobs SET comfy_prompt_id=?, progress='sampling' WHERE id=?", (pid, jid))

    deadline = time.monotonic() + JOB_TIMEOUT
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        with db() as c:
            cur = c.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
        if cur and cur["status"] == "cancelled":
            await comfy_json(session, "POST", "/interrupt", {})
            return
        hist = await comfy_json(session, "GET", f"/history/{pid}")
        entry = hist.get(pid)
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            msgs = status.get("messages", [])
            raise RuntimeError(f"comfy error: {json.dumps(msgs)[:1200]}")
        out = _find_output(entry.get("outputs", {}))
        if out:
            src = COMFY_OUTPUT / out.get("subfolder", "") / out["filename"]
            if not src.is_file():
                raise RuntimeError(f"output missing: {src}")
            dst = VIDEO_DIR / f"{jid}.mp4"
            dst.write_bytes(src.read_bytes())
            with db() as c:
                c.execute("UPDATE jobs SET status='succeeded', output=?, finished_at=?, progress='done' WHERE id=?",
                          (str(dst), time.time(), jid))
            return
    raise TimeoutError(f"job exceeded {JOB_TIMEOUT:.0f}s")


async def worker_loop() -> None:
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                with db() as c:
                    row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
                if not row:
                    await asyncio.sleep(2)
                    continue
                job = dict(row)
                try:
                    await run_job(session, job)
                except Exception as exc:  # noqa: BLE001
                    with db() as c:
                        c.execute("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                                  (str(exc)[:2000], time.time(), job["id"]))
            except Exception:
                await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# api
# ---------------------------------------------------------------------------
app = FastAPI(title="LTX-2.5 Video API", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    asyncio.create_task(worker_loop())


@app.get("/v1/health")
async def health() -> dict[str, Any]:
    try:
        async with aiohttp.ClientSession() as s:
            stats = await comfy_json(s, "GET", "/system_stats")
        devices = stats.get("devices", [])
        comfy = {"ok": True, "vram_free_mb": [round(d.get("vram_free", 0) / 1e6) for d in devices]}
    except Exception as exc:  # noqa: BLE001
        comfy = {"ok": False, "error": str(exc)[:200]}
    with db() as c:
        q = c.execute("SELECT COUNT(*) n FROM jobs WHERE status='queued'").fetchone()["n"]
        r = c.execute("SELECT COUNT(*) n FROM jobs WHERE status='running'").fetchone()["n"]
    return {"status": "ok", "comfy": comfy, "queue": q, "running": r}


@app.post("/v1/videos", dependencies=[Depends(require_token)])
async def create_video(req: VideoRequest) -> dict[str, Any]:
    try:
        w, h = (int(x) for x in req.size.lower().split("x"))
    except ValueError:
        raise HTTPException(status_code=422, detail="size must be WxH")
    w, h = (w // 64) * 64, (h // 64) * 64
    frames = max(9, int(round(req.seconds * req.fps)))
    frames = ((frames - 1) // 8) * 8 + 1
    seed = req.seed if req.seed is not None else int.from_bytes(os.urandom(4), "big") % (2**31)
    mode = "i2v" if req.first_frame else "t2v"
    jid = uuid.uuid4().hex
    now = time.time()
    with db() as c:
        c.execute(
            """INSERT INTO jobs (id, status, model, prompt, negative, width, height, frames, fps, seconds,
               seed, audio, mode, request_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (jid, "queued", req.model, req.prompt, req.negative, w, h, frames, req.fps, req.seconds,
             seed, int(req.audio), mode, req.model_dump_json(), now),
        )
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return row_to_public(row)


@app.get("/v1/videos", dependencies=[Depends(require_token)])
async def list_videos(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    with db() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"object": "list", "data": [row_to_public(r) for r in rows]}


@app.get("/v1/videos/{video_id}", dependencies=[Depends(require_token)])
async def get_video(video_id: str) -> dict[str, Any]:
    with db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return row_to_public(row)


@app.get("/v1/videos/{video_id}/content", dependencies=[Depends(require_token)])
async def get_content(video_id: str) -> FileResponse:
    with db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (video_id,)).fetchone()
    if not row or row["status"] != "succeeded" or not row["output"]:
        raise HTTPException(status_code=404, detail="not ready")
    return FileResponse(row["output"], media_type="video/mp4", filename=f"{video_id}.mp4")


@app.post("/v1/videos/{video_id}/cancel", dependencies=[Depends(require_token)])
async def cancel_video(video_id: str) -> dict[str, Any]:
    with db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        if row["status"] in ("queued", "running"):
            c.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (time.time(), video_id))
    return {"id": video_id, "status": "cancelled"}


@app.delete("/v1/videos/{video_id}", dependencies=[Depends(require_token)])
async def delete_video(video_id: str) -> dict[str, Any]:
    with db() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (video_id,))
    return {"id": video_id, "deleted": True}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
