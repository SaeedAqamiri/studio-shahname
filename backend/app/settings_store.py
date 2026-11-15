"""Runtime-configurable provider settings.

Defaults come from the environment (.env); anything saved from the UI is
stored in the app_settings table and wins over the defaults.  Secrets are
never returned by the API: GET reports api_key_set instead.
"""

from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from . import config
from .models import AppSetting

SECTIONS = ("image", "video", "tts", "llm")

DEFAULTS: dict[str, dict] = {
    "image": {
        "provider": config.IMAGE_PROVIDER,
        "base_url": config.FLUX_API_BASE if config.IMAGE_PROVIDER == "flux_gateway" else config.OPENAI_IMAGE_BASE,
        "model": config.OPENAI_IMAGE_MODEL,
        "edit_base_url": config.IMAGE_EDIT_BASE,
        "api_key": "",
    },
    "video": {
        "provider": config.VIDEO_PROVIDER,
        "base_url": config.VIDEO_API_BASE,
        "model": "ltx-2.5",
        "api_key": "",
    },
    "tts": {
        "provider": config.TTS_PROVIDER,
        "base_url": config.LLM_BASE,
        "model": config.TTS_MODEL,
        "api_key": config.AVALAI_KEY,
        "default_voice": config.PIPER_VOICE,
    },
    "llm": {
        "provider": "openai",
        "base_url": config.LLM_BASE,
        "model": config.LLM_MODEL,
        "api_key": config.AVALAI_KEY,
    },
}


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if k in SECTIONS and isinstance(v, dict):
            out.setdefault(k, {}).update(v)
        else:
            out[k] = v
    return out


def get_raw(db: Session) -> dict:
    stored = {}
    for row in db.query(AppSetting).all():
        stored[row.key] = row.value or {}
    return _merge(DEFAULTS, stored)


def get_public(db: Session) -> dict:
    cfg = copy.deepcopy(get_raw(db))
    for sec in SECTIONS:
        data = cfg.get(sec, {})
        data["api_key_set"] = bool(data.get("api_key"))
        data["api_key"] = ""
    return cfg


def save(db: Session, patch: dict) -> dict:
    merged = _merge(get_raw(db), patch)
    for sec in SECTIONS:
        data = merged.get(sec, {})
        if not data.get("api_key"):
            # keep the previously stored key when the UI sends an empty value
            prev = get_raw(db).get(sec, {})
            data["api_key"] = prev.get("api_key", "")
        row = db.get(AppSetting, sec)
        if row:
            row.value = data
        else:
            db.add(AppSetting(key=sec, value=data))
    db.commit()
    return get_public(db)


def section(db: Session, name: str) -> dict:
    cfg = get_raw(db)
    return cfg.get(name, {})
