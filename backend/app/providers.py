"""Provider adapters. Every adapter is configured at call time from the
runtime settings, so providers can be swapped from the studio UI."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from . import config


def _data_url(raw: bytes, mime: str | None = None) -> str:
    if not mime:
        mime = "image/png"
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:4] == b"RIFF":
            mime = "image/webp"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _auth(key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


class ImageProvider:
    name = "base"

    async def generate(self, prompt: str, negative: str, width: int, height: int,
                       seed: int | None = None, references: list[bytes] | None = None) -> bytes:
        raise NotImplementedError


class FluxGatewayProvider(ImageProvider):
    name = "flux_gateway"

    def __init__(self, base: str, edit_base: str | None = None):
        self.base = base.rstrip("/")
        self.edit_base = (edit_base or config.IMAGE_EDIT_BASE).rstrip("/")

    async def generate(self, prompt: str, negative: str, width: int, height: int,
                       seed: int | None = None, references: list[bytes] | None = None) -> bytes:
        body: dict[str, Any] = {
            "prompt": prompt, "negative": negative, "width": width, "height": height,
            "filename_prefix": "studio/char",
        }
        if seed is not None:
            body["seed"] = int(seed)
        if references:
            body["references"] = [_data_url(r) for r in references]
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(self.base + "/v1/generate", params={"wait": "true", "timeout": 540}, json=body)
            r.raise_for_status()
            job = r.json()
            if job.get("status") != "succeeded":
                raise RuntimeError(job.get("error") or f"image job {job.get('status')}")
            img = await client.get(self.base + job["image_url"])
            img.raise_for_status()
            return img.content

    async def edit(self, prompt: str, negative: str, image: bytes, mask: bytes,
                   seed: int | None = None, steps: int = 20, denoise: float = 0.9) -> bytes:
        files = {"image": ("image.png", image, "image/png"),
                 "mask": ("mask.png", mask, "image/png")}
        data = {"prompt": prompt, "negative": negative, "steps": str(steps), "denoise": str(denoise)}
        if seed is not None:
            data["seed"] = str(seed)
        async with httpx.AsyncClient(timeout=900) as client:
            r = await client.post(self.edit_base + "/v1/images/edits", files=files, data=data)
            r.raise_for_status()
            item = (r.json().get("data") or [{}])[0]
            if not item.get("b64_json"):
                raise RuntimeError("edit provider returned no image")
            return base64.b64decode(item["b64_json"])


class OpenAIImagesProvider(ImageProvider):
    name = "openai_images"

    async def edit(self, prompt: str, negative: str, image: bytes, mask: bytes,
                   seed: int | None = None, steps: int = 20, denoise: float = 0.9) -> bytes:
        files = [("image", ("image.png", image, "image/png")), ("mask", ("mask.png", mask, "image/png"))]
        data = {"model": self.model, "prompt": prompt, "size": "1024x1024", "n": "1", "response_format": "b64_json"}
        async with httpx.AsyncClient(timeout=900) as client:
            r = await client.post(self.base + "/images/edits", headers=_auth(self.key), data=data, files=files)
            r.raise_for_status()
            return self._parse(r.json())

    def __init__(self, base: str, model: str, key: str):
        self.base, self.model, self.key = base.rstrip("/"), model, key

    async def generate(self, prompt: str, negative: str, width: int, height: int,
                       seed: int | None = None, references: list[bytes] | None = None) -> bytes:
        if references:
            data = {"model": self.model, "prompt": prompt, "size": f"{width}x{height}", "n": "1"}
            files = [("image", ("ref.png", references[0], "image/png"))]
            async with httpx.AsyncClient(timeout=600) as client:
                r = await client.post(self.base + "/images/edits", headers=_auth(self.key), data=data, files=files)
                r.raise_for_status()
                return self._parse(r.json())
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt + (("\nAvoid: " + negative) if negative else ""),
            "size": f"{width}x{height}", "n": 1, "response_format": "b64_json",
        }
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(self.base + "/images/generations", headers=_auth(self.key), json=body)
            r.raise_for_status()
            return self._parse(r.json())

    @staticmethod
    def _parse(payload: dict[str, Any]) -> bytes:
        item = (payload.get("data") or [{}])[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            with httpx.Client(timeout=120) as c:
                return c.get(item["url"]).content
        raise RuntimeError("image provider returned no data")


def get_image_provider(cfg: dict | None = None) -> ImageProvider:
    cfg = cfg or {}
    provider = cfg.get("provider", config.IMAGE_PROVIDER)
    base = cfg.get("base_url") or config.FLUX_API_BASE
    if provider == "openai_images":
        return OpenAIImagesProvider(base, cfg.get("model") or config.OPENAI_IMAGE_MODEL, cfg.get("api_key", ""))
    return FluxGatewayProvider(base, cfg.get("edit_base_url"))


class LLM:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.base = (cfg.get("base_url") or config.LLM_BASE).rstrip("/")
        self.model = cfg.get("model") or config.LLM_MODEL
        self.key = cfg.get("api_key") or config.AVALAI_KEY

    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.7,
                   json_mode: bool = False, max_tokens: int = 4000) -> str:
        body: dict[str, Any] = {
            "model": self.model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(self.base + "/chat/completions", headers=_auth(self.key), json=body)
            r.raise_for_status()
            data = r.json()
            msg = data["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning_content") or ""


class TTS:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.provider = cfg.get("provider", config.TTS_PROVIDER)
        self.base = (cfg.get("base_url") or config.LLM_BASE).rstrip("/")
        self.model = cfg.get("model") or config.TTS_MODEL
        self.key = cfg.get("api_key") or config.AVALAI_KEY
        self.default_voice = cfg.get("default_voice") or config.PIPER_VOICE

    async def speak(self, text: str, voice: str | None = None, language: str = "fa",
                    speed: float = 1.0) -> tuple[bytes, str]:
        voice = voice or self.default_voice
        if self.provider == "piper":
            return await self._piper(text, voice, speed)
        if self.provider == "fish":
            return await self._fish(text, voice)
        if self.provider == "ltx":
            raise RuntimeError("LTX voice cloning is applied during video rendering, not as a standalone TTS. "
                               "Pick a reference audio on the character; it will be used by LTXReferenceAudio.")
        return await self._openai(text, voice, speed)

    async def _openai(self, text: str, voice: str, speed: float) -> tuple[bytes, str]:
        body = {"model": self.model, "voice": voice, "input": text, "response_format": "mp3", "speed": speed}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(self.base + "/audio/speech", headers=_auth(self.key), json=body)
            r.raise_for_status()
            return r.content, "mp3"

    async def _fish(self, text: str, voice: str) -> tuple[bytes, str]:
        body = {"text": text, "reference_id": voice or None, "format": "mp3"}
        async with httpx.AsyncClient(timeout=900) as client:
            r = await client.post(self.base + "/v1/tts", headers=_auth(self.key), json=body)
            r.raise_for_status()
            return r.content, "mp3"

    async def clone_fish(self, audio: bytes, transcript: str, ref_id: str,
                         filename: str = "reference.wav") -> str:
        files = {"audio": (filename, audio, "audio/wav")}
        data = {"id": ref_id, "text": transcript}
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(self.base + "/v1/references/add", headers=_auth(self.key),
                                  data=data, files=files)
            r.raise_for_status()
        return ref_id

    async def _piper(self, text: str, voice: str, speed: float) -> tuple[bytes, str]:
        exe = shutil.which("piper") or str(Path.home() / ".local/bin/piper")
        model = Path(config.DATA) / "voices" / f"{voice}.onnx"
        if not Path(exe).is_file():
            raise RuntimeError("piper binary not found")
        if not model.is_file():
            raise RuntimeError(f"voice model missing: {model}")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        proc = subprocess.run(
            [exe, "--model", str(model), "--length_scale", str(1.0 / max(0.25, speed)), "--output_file", out],
            input=text.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError("piper failed: " + proc.stderr.decode()[-400:])
        return Path(out).read_bytes(), "wav"


def get_llm(cfg: dict | None = None) -> LLM:
    return LLM(cfg)


def get_tts(cfg: dict | None = None) -> TTS:
    return TTS(cfg)


class VideoAPI:
    """OpenAI-Videos compatible client (our LTX gateway or any Sora-like API)."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.base = (cfg.get("base_url") or config.VIDEO_API_BASE).rstrip("/")
        self.key = cfg.get("api_key") or ""
        self.model = cfg.get("model") or "ltx-2.5"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    async def submit(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(self.base + "/v1/videos", headers=self._headers(), json=payload)
            r.raise_for_status()
            return r.json()

    async def get(self, job_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(self.base + f"/v1/videos/{job_id}", headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def content(self, job_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.get(self.base + f"/v1/videos/{job_id}/content", headers=self._headers())
            r.raise_for_status()
            return r.content

    async def cancel(self, job_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.base + f"/v1/videos/{job_id}/cancel", headers=self._headers())
            r.raise_for_status()
            return r.json()


def get_video_api(cfg: dict | None = None) -> VideoAPI:
    return VideoAPI(cfg)
