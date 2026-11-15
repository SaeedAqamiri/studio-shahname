"""Mask-based image editing (inpainting) on top of ComfyUI + Flux.

OpenAI-compatible endpoint:

    POST /v1/images/edits   multipart: image, mask, prompt, negative?, steps?, seed?, denoise?
    GET  /v1/health

Only the masked region is regenerated; the rest of the image is preserved by
the latent noise mask. Runs next to the existing generation gateway.
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import time
import uuid
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_INPUT = Path(os.environ.get("COMFY_INPUT_DIR", "/home/ava/flux3-klein/comfy_input"))
COMFY_OUTPUT = Path(os.environ.get("COMFY_OUTPUT_DIR", "/home/ava/flux3-klein/comfy_output"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8092"))

UNET = "flux3-image-klein-int8-convrot.safetensors"
CLIP = "qwen3vl_4b_int8_convrot.safetensors"
VAE = "flux2-vae.safetensors"

app = FastAPI(title="Flux edit API", version="0.1.0")


def _prepare(image: bytes, mask: bytes, max_side: int = 1536) -> tuple[Image.Image, Image.Image]:
    img = Image.open(io.BytesIO(image)).convert("RGB")
    msk = Image.open(io.BytesIO(mask)).convert("L")
    if msk.size != img.size:
        msk = msk.resize(img.size, Image.LANCZOS)
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    nw, nh = int(w * scale), int(h * scale)
    nw, nh = max(32, nw // 32 * 32), max(32, nh // 32 * 32)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.LANCZOS)
        msk = msk.resize((nw, nh), Image.LANCZOS)
    return img, msk


def _graph(prompt: str, negative: str, width: int, height: int, steps: int,
           seed: int, denoise: float, img_name: str, mask_name: str, prefix: str) -> dict:
    shift = math.log(16.0)
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "flux3", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "LoadImage", "inputs": {"image": img_name}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "9": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["7", 0], "mask": ["8", 0]}},
        "10": {"class_type": "ModelSamplingFlux", "inputs": {"model": ["1", 0], "max_shift": shift,
                                                             "base_shift": shift, "width": width, "height": height}},
        "11": {"class_type": "KSampler", "inputs": {
            "model": ["10", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["9", 0], "denoise": denoise}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    }


@app.get("/v1/health")
async def health():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(COMFY_URL + "/system_stats", timeout=aiohttp.ClientTimeout(total=5)) as r:
                return {"status": "ok", "comfy": r.status == 200}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "error": str(exc)[:200]}


@app.post("/v1/images/edits")
async def edit(
    image: UploadFile = File(...),
    mask: UploadFile = File(...),
    prompt: str = Form(...),
    negative: str = Form(""),
    steps: int = Form(20),
    seed: int | None = Form(None),
    denoise: float = Form(0.9),
):
    img, msk = _prepare(await image.read(), await mask.read())
    w, h = img.size
    seed = seed if seed is not None else int.from_bytes(os.urandom(4), "big") % (2**31)
    tag = uuid.uuid4().hex[:12]
    img_name = f"edit_{tag}_img.png"
    mask_name = f"edit_{tag}_mask.png"
    img.save(COMFY_INPUT / img_name, format="PNG")
    msk.save(COMFY_INPUT / mask_name, format="PNG")
    prefix = f"studio/edit_{tag}"

    graph = _graph(prompt, negative, w, h, max(1, min(steps, 60)), seed, denoise, img_name, mask_name, prefix)
    async with aiohttp.ClientSession() as s:
        async with s.post(COMFY_URL + "/prompt", json={"prompt": graph, "client_id": tag},
                          timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.json()
            if r.status >= 400:
                raise HTTPException(502, f"comfy rejected: {str(data)[:600]}")
            pid = data["prompt_id"]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            async with s.get(COMFY_URL + f"/history/{pid}", timeout=aiohttp.ClientTimeout(total=30)) as r:
                hist = await r.json()
            entry = hist.get(pid)
            if not entry:
                continue
            status = entry.get("status", {}).get("status_str")
            if status == "error":
                raise HTTPException(502, "comfy error: " + str(entry.get("status", {}).get("messages"))[:500])
            out = entry.get("outputs", {}).get("13", {}).get("images", [])
            if out:
                item = out[0]
                path = COMFY_OUTPUT / item.get("subfolder", "") / item["filename"]
                if not path.is_file():
                    raise HTTPException(500, "output missing")
                b64 = base64.b64encode(path.read_bytes()).decode()
                return JSONResponse({"created": int(time.time()), "data": [{"b64_json": b64}],
                                     "size": f"{w}x{h}", "seed": seed})
        raise HTTPException(504, "edit timed out")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
