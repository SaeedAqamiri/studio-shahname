from __future__ import annotations

import asyncio
import json
import random
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import get_db
from .. import config
from ..models import Asset, CastMember, Character, Project, Render, Scene, Shot, WardrobeVariant
from ..providers import get_image_provider, get_llm, get_tts
from ..services.audio import concat_audio
from ..services.assets import asset_url, save_asset
from ..services.prompting import scene_prompt
from ..services.video import extract_frame

router = APIRouter(tags=["scenes"])


class CastIn(BaseModel):
    character_id: str
    variant_id: str | None = None
    role_in_scene: str = ""
    prompt_delta: str = ""


class LookIn(BaseModel):
    prompt: str = ""
    width: int = Field(default=1280, ge=384, le=1536)
    height: int = Field(default=720, ge=384, le=1536)
    seed: int | None = None
    use_cast_references: bool = True


class ShotIn(BaseModel):
    prompt: str = ""
    mode: str = "auto"  # auto | t2v | i2v
    width: int = Field(default=1280, ge=384, le=1536)
    height: int = Field(default=720, ge=384, le=1536)
    seconds: float = Field(default=4.0, ge=1.0, le=20.0)
    fps: float = Field(default=24.0, ge=8.0, le=30.0)
    seed: int | None = None
    audio: bool = True
    first_frame_asset_id: str | None = None


def cast_public(db: Session, c: CastMember) -> dict:
    ch = db.get(Character, c.character_id)
    v = db.get(WardrobeVariant, c.variant_id) if c.variant_id else None
    return {
        "id": c.id, "character_id": c.character_id, "character_name": ch.name if ch else "",
        "variant_id": c.variant_id, "variant_name": v.name if v else None,
        "role_in_scene": c.role_in_scene, "prompt_delta": c.prompt_delta,
        "reference_url": asset_url(ch.canonical_image_id) if ch else None,
    }


def shot_public(db: Session, s: Shot) -> dict:
    return {
        "id": s.id, "scene_id": s.scene_id, "index": s.index, "prompt": s.prompt,
        "negative": s.negative, "mode": s.mode, "width": s.width, "height": s.height,
        "fps": s.fps, "seconds": s.seconds, "seed": s.seed, "generate_audio": s.generate_audio,
        "first_frame_id": s.first_frame_id, "first_frame_url": asset_url(s.first_frame_id),
        "last_frame_id": s.last_frame_id, "status": s.status,
    }


def scene_detail(db: Session, scene: Scene) -> dict:
    project = db.get(Project, scene.script.project_id) if scene.script else None
    cast = db.query(CastMember).filter(CastMember.scene_id == scene.id).all()
    shots = db.query(Shot).filter(Shot.scene_id == scene.id).order_by(Shot.index).all()
    return {
        "id": scene.id, "script_id": scene.script_id, "index": scene.index, "heading": scene.heading,
        "location": scene.location, "time_of_day": scene.time_of_day, "summary": scene.summary,
        "action_text": scene.action_text, "dialogue": scene.dialogue or [],
        "style_overrides": scene.style_overrides or {}, "prev_scene_id": scene.prev_scene_id,
        "status": scene.status, "look_frame_id": scene.look_frame_id,
        "look_frame_url": asset_url(scene.look_frame_id),
        "visual_prompt": (scene.style_overrides or {}).get("visual_prompt", ""),
        "negative": (scene.style_overrides or {}).get("negative", ""),
        "style": project.style_bible if project else {},
        "cast": [cast_public(db, c) for c in cast],
        "shots": [shot_public(db, s) for s in shots],
    }


@router.get("/api/scenes/{scene_id}")
def get_scene(scene_id: str, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    return scene_detail(db, scene)


@router.post("/api/scenes/{scene_id}/cast")
def add_cast(scene_id: str, body: CastIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Scene, scene_id):
        raise HTTPException(404, "scene not found")
    if not db.get(Character, body.character_id):
        raise HTTPException(404, "character not found")
    existing = db.query(CastMember).filter(CastMember.scene_id == scene_id,
                                          CastMember.character_id == body.character_id).first()
    if existing:
        existing.variant_id = body.variant_id
        existing.role_in_scene = body.role_in_scene
        existing.prompt_delta = body.prompt_delta
        db.commit()
        return cast_public(db, existing)
    c = CastMember(scene_id=scene_id, **body.model_dump())
    db.add(c)
    db.commit()
    return cast_public(db, c)


@router.delete("/api/scenes/{scene_id}/cast/{cast_id}")
def remove_cast(scene_id: str, cast_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(CastMember, cast_id)
    if not c or c.scene_id != scene_id:
        raise HTTPException(404, "not found")
    db.delete(c)
    db.commit()
    return {"deleted": True}


class DubIn(BaseModel):
    overrides: dict[str, str] = Field(default_factory=dict)


async def build_narration(db: Session, scene: Scene, overrides: dict[str, str] | None = None) -> tuple[str, list]:
    """Render every dialogue line with the matching character voice and join them."""
    tts = get_tts(settings_store.section(db, "tts"))
    overrides = overrides or {}
    cast = db.query(CastMember).filter(CastMember.scene_id == scene.id).all()
    by_name = {}
    for c in cast:
        ch = db.get(Character, c.character_id)
        if ch:
            by_name[ch.name] = ch
    files, lines = [], []
    tmp = Path(tempfile.mkdtemp(prefix="dub_"))
    for i, d in enumerate(scene.dialogue or []):
        text = (d.get("line") or "").strip()
        if not text:
            continue
        speaker = d.get("character") or ""
        ch = by_name.get(speaker)
        voice = overrides.get(speaker)
        if not voice and ch and ch.voice and ch.voice.voice_id:
            voice = ch.voice.voice_id
        raw, ext = await tts.speak(text, voice, "fa")
        f = tmp / f"line_{i}.{ext}"
        f.write_bytes(raw)
        files.append(str(f))
        lines.append({"character": speaker, "line": text, "emotion": d.get("emotion", ""), "file": str(f)})
    if not files:
        return "", []
    out = str(tmp / "narration.wav")
    await concat_audio(files, out)
    return out, lines


SYSTEM_COMPILE = (
    "You are a cinematographer and prompt engineer for the LTX-2.5 video model and Flux image model. "
    "Turn the scene into ONE concrete English shot prompt: subject + characters (matching the cast descriptions), "
    "wardrobe, location, time of day, action, camera move, lens, lighting, mood. "
    "No dialogue in the prompt; keep it under 90 words, concrete and visual. Return ONLY JSON."
)


@router.post("/api/scenes/{scene_id}/compile")
async def compile_scene(scene_id: str, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    project = db.get(Project, scene.script.project_id) if scene.script else None
    cast = db.query(CastMember).filter(CastMember.scene_id == scene.id).all()
    lines = []
    for c in cast:
        ch = db.get(Character, c.character_id)
        v = db.get(WardrobeVariant, c.variant_id) if c.variant_id else None
        if ch:
            ap = ", ".join(f"{k}: {val}" for k, val in (ch.appearance or {}).items() if val)
            lines.append(f"- {ch.name_en or ch.name}: {ch.description}. {ap}" + (f". Extra wardrobe: {v.prompt_delta}" if v else ""))
    user = (
        f"Scene location: {scene.location}\nTime: {scene.time_of_day}\n"
        f"Summary: {scene.summary}\nAction: {scene.action_text}\n"
        f"Dialogue (for context only): {json.dumps(scene.dialogue or [], ensure_ascii=False)}\n"
        f"Cast:\n" + ("\n".join(lines) or "- none") +
        f"\nProject style: {json.dumps(project.style_bible if project else {}, ensure_ascii=False)}\n"
        'Return JSON: {"visual_prompt": string, "negative": string, "camera": string}'
    )
    llm = get_llm(settings_store.section(db, "llm"))
    raw = await llm.chat([{"role": "system", "content": SYSTEM_COMPILE}, {"role": "user", "content": user}],
                        temperature=0.6, json_mode=True, max_tokens=800)
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(502, "LLM returned invalid JSON")
    ov = dict(scene.style_overrides or {})
    ov["visual_prompt"] = data.get("visual_prompt", "")
    ov["negative"] = data.get("negative", "")
    ov["camera"] = data.get("camera", "")
    scene.style_overrides = ov
    db.commit()
    return {"visual_prompt": ov["visual_prompt"], "negative": ov["negative"], "camera": ov["camera"]}


@router.post("/api/scenes/{scene_id}/look-frame")
async def make_look_frame(scene_id: str, body: LookIn, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    project = db.get(Project, scene.script.project_id) if scene.script else None
    ov = scene.style_overrides or {}
    prompt = body.prompt or ov.get("visual_prompt") or scene_prompt(project, scene, [])
    if not prompt.strip():
        raise HTTPException(422, "empty prompt")
    negative = ov.get("negative") or (project.style_bible.get("negative") if project else "") or ""

    refs: list[bytes] = []
    if body.use_cast_references:
        cast = db.query(CastMember).filter(CastMember.scene_id == scene.id).all()
        for c in cast[:4]:
            ch = db.get(Character, c.character_id)
            if ch and ch.canonical_image_id:
                a = db.get(Asset, ch.canonical_image_id)
                if a and Path(a.path).is_file():
                    refs.append(Path(a.path).read_bytes())

    provider = get_image_provider(settings_store.section(db, "image"))
    seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    raw = await provider.generate(prompt, negative, body.width, body.height, seed, refs or None)
    asset = save_asset(db, raw, "image", "png", meta={"scene": scene.id, "kind": "look_frame", "seed": seed, "prompt": prompt})
    scene.look_frame_id = asset.id
    scene.status = "look_ready"
    db.commit()
    return {"look_frame_id": asset.id, "url": asset_url(asset.id), "seed": seed, "prompt": prompt, "references": len(refs)}


@router.post("/api/scenes/{scene_id}/shots")
def upsert_shot(scene_id: str, body: ShotIn, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    ov = scene.style_overrides or {}
    prompt = body.prompt or ov.get("visual_prompt") or scene.summary or scene.heading
    mode = body.mode
    if mode == "auto":
        mode = "i2v" if scene.look_frame_id else "t2v"
    shot = db.query(Shot).filter(Shot.scene_id == scene_id).order_by(Shot.index).first()
    if not shot:
        shot = Shot(scene_id=scene_id, index=1)
        db.add(shot)
    shot.prompt = prompt
    shot.negative = ov.get("negative", "")
    shot.mode = mode
    shot.width, shot.height = body.width, body.height
    shot.seconds, shot.fps = body.seconds, body.fps
    shot.seed = body.seed
    shot.generate_audio = body.audio
    if body.first_frame_asset_id:
        shot.first_frame_id = body.first_frame_asset_id
        shot.mode = "i2v"
    else:
        shot.first_frame_id = scene.look_frame_id if mode == "i2v" else None
    shot.status = "ready"
    cast = db.query(CastMember).filter(CastMember.scene_id == scene_id).all()
    shot.cast_snapshot = [{"character_id": c.character_id, "variant_id": c.variant_id} for c in cast]
    db.commit()
    return shot_public(db, shot)


@router.post("/api/scenes/{scene_id}/prev-frame")
async def prev_frame(scene_id: str, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    if not scene.prev_scene_id:
        raise HTTPException(400, "scene has no previous scene")
    prev = db.get(Scene, scene.prev_scene_id)
    if not prev:
        raise HTTPException(404, "previous scene not found")
    shot = db.query(Shot).filter(Shot.scene_id == prev.id).order_by(Shot.index).first()
    if not shot:
        raise HTTPException(404, "previous scene has no shot")
    render = (db.query(Render).filter(Render.shot_id == shot.id, Render.status == "succeeded",
                                      Render.video_asset_id.isnot(None))
              .order_by(Render.created_at.desc()).first())
    if not render:
        raise HTTPException(404, "previous scene has no finished render")
    asset = db.get(Asset, render.video_asset_id)
    if not asset or not Path(asset.path).is_file():
        raise HTTPException(404, "video asset missing")
    out = config.ASSETS / f"prev_{render.id}.png"
    await extract_frame(asset.path, str(out), last=True)
    img = save_asset(db, out.read_bytes(), "image", "png",
                     meta={"kind": "prev_frame", "render": render.id, "scene": scene.id})
    db.commit()
    return {"asset_id": img.id, "url": asset_url(img.id), "from_scene_index": prev.index,
            "from_scene_heading": prev.heading}


@router.post("/api/scenes/{scene_id}/dub")
async def dub_scene(scene_id: str, body: DubIn, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    path, lines = await build_narration(db, scene, body.overrides)
    if not path:
        raise HTTPException(422, "scene has no dialogue")
    raw = Path(path).read_bytes()
    asset = save_asset(db, raw, "audio", "wav", mime="audio/wav",
                       meta={"scene": scene.id, "kind": "narration", "lines": len(lines)})
    db.commit()
    return {"audio_asset_id": asset.id, "url": asset_url(asset.id), "lines": len(lines),
            "texts": [l["line"] for l in lines]}
