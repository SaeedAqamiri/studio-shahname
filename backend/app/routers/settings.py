from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import get_db
from ..providers import LLM, TTS, get_image_provider

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    image: dict | None = None
    video: dict | None = None
    tts: dict | None = None
    llm: dict | None = None


class TestIn(BaseModel):
    section: str = Field(pattern="^(image|video|tts|llm)$")
    config: dict = Field(default_factory=dict)


def _auth(key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"} if key else {}


def _ok(started: float, extra: dict) -> dict:
    return {"ok": True, "ms": round((time.monotonic() - started) * 1000), **extra}


@router.get("")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return settings_store.get_public(db)


@router.put("")
def put_settings(body: SettingsPatch, db: Session = Depends(get_db)) -> dict:
    return settings_store.save(db, body.model_dump(exclude_none=True))


@router.post("/test")
async def test_provider(body: TestIn, db: Session = Depends(get_db)) -> dict:
    cfg = {**settings_store.section(db, body.section), **(body.config or {})}
    started = time.monotonic()
    try:
        if body.section == "image":
            p = get_image_provider(cfg)
            if p.name == "flux_gateway":
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(str(cfg["base_url"]).rstrip("/") + "/v1/health")
                    r.raise_for_status()
                    return _ok(started, {"workers": r.json().get("workers")})
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(str(cfg["base_url"]).rstrip("/") + "/models", headers=_auth(cfg.get("api_key")))
                r.raise_for_status()
                return _ok(started, {"models": len(r.json().get("data", []))})
        if body.section == "video":
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(str(cfg["base_url"]).rstrip("/") + "/v1/health")
                r.raise_for_status()
                return _ok(started, r.json())
        if body.section == "tts":
            t = TTS(cfg)
            raw, fmt = await t.speak("سلام", cfg.get("default_voice"))
            return _ok(started, {"bytes": len(raw), "format": fmt})
        if body.section == "llm":
            text = await LLM(cfg).chat([{"role": "user", "content": "فقط بنویس: سلام"}], max_tokens=10)
            return _ok(started, {"reply": text[:80]})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)[:400], "ms": round((time.monotonic() - started) * 1000)}
    return {"ok": False, "detail": "unknown section"}
