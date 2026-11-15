from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Character, VoiceProfile
from ..services.assets import asset_url, save_asset
from ..providers import get_tts
from .. import settings_store

router = APIRouter(tags=["voices"])

CATALOG = {
    "piper": {
        "label": "Piper — محلی و رایگان (بدون کلون)",
        "language": "fa",
        "voices": [
            {"id": "fa_IR-amir-medium", "name": "امیر — مرد، گرم", "gender": "male"},
            {"id": "fa_IR-gyro-medium", "name": "گایرو — مرد، خبری", "gender": "male"},
        ],
    },
    "avalai": {
        "label": "AvalAI / سازگار با OpenAI (نیازمند فعال‌بودن مدل TTS)",
        "language": "multi",
        "voices": [
            {"id": "coral", "name": "Coral", "gender": "female"},
            {"id": "marin", "name": "Marin", "gender": "female"},
            {"id": "cedar", "name": "Cedar", "gender": "male"},
            {"id": "onyx", "name": "Onyx", "gender": "male"},
            {"id": "shimmer", "name": "Shimmer", "gender": "female"},
        ],
    },
    "fish": {
        "label": "Fish Audio — کلون صدا (نیازمند کلید)",
        "language": "multi",
        "voices": [],
    },
    "elevenlabs": {
        "label": "ElevenLabs — کلون صدا (نیازمند کلید)",
        "language": "multi",
        "voices": [],
    },
    "ltx": {
        "label": "LTX-2.5 — کلون با صدای مرجع (داخل ویدیو)",
        "language": "multi",
        "voices": [],
    },
}


class VoiceIn(BaseModel):
    provider: str = Field(default="piper")
    voice_id: str = ""
    language: str = "fa"
    settings: dict = Field(default_factory=dict)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1)
    voice: str | None = None
    language: str = "fa"


@router.get("/api/voices")
def list_voices() -> dict:
    return {"data": CATALOG}


@router.put("/api/characters/{character_id}/voice")
def set_voice(character_id: str, body: VoiceIn, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    vp = db.query(VoiceProfile).filter(VoiceProfile.character_id == character_id).one_or_none()
    if not vp:
        vp = VoiceProfile(character_id=character_id)
        db.add(vp)
    vp.provider, vp.voice_id, vp.language, vp.settings = body.provider, body.voice_id, body.language, body.settings
    db.commit()
    return {"provider": vp.provider, "voice_id": vp.voice_id, "language": vp.language, "settings": vp.settings}


@router.post("/api/tts/preview")
async def preview(body: SpeakIn, db: Session = Depends(get_db)) -> dict:
    tts = get_tts(settings_store.section(db, "tts"))
    raw, ext = await tts.speak(body.text, body.voice, body.language)
    return {"audio_b64": __import__("base64").b64encode(raw).decode(), "format": ext}


@router.post("/api/characters/{character_id}/voice/reference")
async def upload_reference(character_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "audio too large")
    ext = (file.filename or "ref.wav").rsplit(".", 1)[-1].lower()
    if ext not in ("wav", "mp3", "m4a", "ogg", "flac", "webm"):
        ext = "wav"
    asset = save_asset(db, raw, "audio", ext, mime=file.content_type or "audio/wav",
                       meta={"character": character_id, "kind": "voice_reference"})
    vp = db.query(VoiceProfile).filter(VoiceProfile.character_id == character_id).one_or_none()
    if not vp:
        vp = VoiceProfile(character_id=character_id)
        db.add(vp)
    vp.reference_audio_id = asset.id
    vp.provider = "ltx"
    db.commit()
    return {"reference_audio_id": asset.id, "url": asset_url(asset.id), "provider": vp.provider}


@router.post("/api/characters/{character_id}/voice/clone")
async def clone_voice(character_id: str, file: UploadFile = File(...), transcript: str = Form(...),
                      db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    raw = await file.read()
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "audio too large")
    if len(transcript.strip()) < 5:
        raise HTTPException(422, "reference transcript is too short")
    cfg = settings_store.section(db, "tts")
    asset = save_asset(db, raw, "audio", (file.filename or "ref.wav").rsplit(".", 1)[-1],
                       mime=file.content_type or "audio/wav",
                       meta={"character": character_id, "kind": "clone_reference"})
    vp = db.query(VoiceProfile).filter(VoiceProfile.character_id == character_id).one_or_none()
    if not vp:
        vp = VoiceProfile(character_id=character_id)
        db.add(vp)
    vp.reference_audio_id = asset.id
    if cfg.get("provider") == "fish":
        ref_id = f"char_{character_id[:8]}_{int(__import__('time').time())}"
        await get_tts(cfg).clone_fish(raw, transcript, ref_id, file.filename or "reference.wav")
        vp.provider, vp.voice_id, vp.language = "fish", ref_id, "fa"
    else:
        vp.provider = "ltx"
    db.commit()
    return {"provider": vp.provider, "voice_id": vp.voice_id, "reference_audio_id": asset.id,
            "url": asset_url(asset.id)}
