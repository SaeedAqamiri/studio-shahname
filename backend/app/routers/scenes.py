from __future__ import annotations

import asyncio
import base64
import json
import random
import re
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
from ..services import pacing
from ..services.audio import concat_audio
from ..services.assets import asset_url, save_asset
from ..services.prompting import scene_prompt
from ..services.shots import (
    MANUAL_FRAME_KIND,
    chain_from_previous,
    is_manual_first_frame,
    last_succeeded_render,
    ordered_shots,
    renumber,
)
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


class TranslateIn(BaseModel):
    text: str = ""
    save: bool = True
    target: str = "both"  # both | keyframe | video


class LookEditIn(BaseModel):
    mask: str  # PNG data URL
    prompt: str = Field(min_length=1)
    negative: str = ""
    steps: int = Field(default=20, ge=1, le=60)
    seed: int | None = None
    denoise: float = Field(default=0.9, ge=0.3, le=1.0)


class ShotIn(BaseModel):
    index: int | None = Field(default=None, ge=1)
    prompt: str = ""
    mode: str = "auto"  # auto | t2v | i2v
    width: int = Field(default=1280, ge=384, le=1536)
    height: int = Field(default=720, ge=384, le=1536)
    seconds: float = Field(default=4.0, ge=1.0, le=20.0)
    fps: float = Field(default=24.0, ge=8.0, le=30.0)
    seed: int | None = None
    audio: bool = True
    first_frame_asset_id: str | None = None


class ProposeShotsIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=8)


class ShotsApplyIn(BaseModel):
    shots: list[dict] = Field(default_factory=list)
    replace: bool = False


class ShotFirstFrameInpaintIn(BaseModel):
    mask: str  # PNG data URL
    prompt: str = Field(min_length=1)
    negative: str = ""
    steps: int = Field(default=20, ge=1, le=60)
    seed: int | None = None
    denoise: float = Field(default=0.9, ge=0.3, le=1.0)


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
    render = (
        db.query(Render)
        .filter(Render.shot_id == s.id)
        .order_by(Render.created_at.desc())
        .first()
    )
    return {
        "id": s.id, "scene_id": s.scene_id, "index": s.index, "prompt": s.prompt,
        "negative": s.negative, "mode": s.mode, "width": s.width, "height": s.height,
        "fps": s.fps, "seconds": s.seconds, "seed": s.seed, "generate_audio": s.generate_audio,
        "first_frame_id": s.first_frame_id, "first_frame_url": asset_url(s.first_frame_id),
        "first_frame_manual": is_manual_first_frame(db, s),
        "last_frame_id": s.last_frame_id, "status": s.status,
        "last_render": {
            "id": render.id, "status": render.status, "error": render.error,
            "video_url": asset_url(render.video_asset_id),
        } if render else None,
    }


def _shot_defaults(db: Session, scene: Scene, shot: Shot | None = None) -> tuple[str, float, str]:
    ov = scene.style_overrides or {}
    prompt = (shot.prompt if shot else "") or ov.get("video_prompt") or ov.get("visual_prompt") \
        or scene.summary or scene.heading
    profile = pacing.get_profile(ov.get("pacing_profile") or pacing.DEFAULT_PROFILE)
    seconds = (shot.seconds if shot else 0) or ov.get("duration_sec") or sum(profile["shot_duration"]) / 2
    negative = ov.get("video_negative") or ov.get("negative") or ""
    return prompt, float(seconds), negative


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
        "visual_prompt_fa": (scene.style_overrides or {}).get("visual_prompt_fa", ""),
        "keyframe_prompt": (scene.style_overrides or {}).get("keyframe_prompt", ""),
        "video_prompt": (scene.style_overrides or {}).get("video_prompt", ""),
        "video_negative": (scene.style_overrides or {}).get("video_negative", ""),
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


GEMINI_TTS_VOICES = ["Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"]


async def build_narration(db: Session, scene: Scene, overrides: dict[str, str] | None = None) -> tuple[str, list]:
    """Render every dialogue line with the matching character voice and join them."""
    cfg = settings_store.section(db, "tts")
    tts = get_tts(cfg)
    provider = (cfg.get("provider") or "").lower()
    default_voice = (cfg.get("default_voice") or "").strip()
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
            vid = ch.voice.voice_id
            if provider == "openai":
                # hosted TTS (Gemini) only accepts its own voice names; ignore old
                # cloned/reference ids such as fish's "char_..." values
                if vid in GEMINI_TTS_VOICES:
                    voice = vid
                elif vid and not vid.startswith("char_"):
                    voice = vid
            else:
                voice = vid
        if not voice and provider == "openai":
            voice = default_voice or GEMINI_TTS_VOICES[0]
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


def _parse_llm_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    dec = json.JSONDecoder()
    last = None
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
            if isinstance(obj, dict):
                last = obj
        except Exception:
            continue
    if last is not None:
        return last
    raise ValueError("no JSON object found")


LTX_NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, flicker, morphing, warped limbs"

SYSTEM_COMPILE = (
    "You are a cinematographer, bilingual screenwriter and prompt engineer working with Flux (still image) and "
    "LTX-2.5 (image-to-video / text-to-video). Produce all of the following for ONE scene.\n"
    "1) visual_prompt_fa: a natural Persian visual description (1-3 sentences) a Persian director can read and edit: "
    "place, time, characters, action and mood. No dialogue, no on-screen text.\n"
    "2) keyframe_prompt: an English prompt for Flux describing ONE FROZEN cinematic frame: shot size, subjects with their "
    "English names and exact wardrobe/appearance, environment, composition, lens, lighting, palette, mood. "
    "No camera movement, no motion verbs, no temporal change, no dialogue. 60-90 words.\n"
    "3) video_prompt: an English prompt for LTX-2.5. ONE flowing paragraph of max 120 words that starts directly with the "
    "main action in the first sentence, then covers chronological motion and gestures, secondary motion (cloth, hair, dust, "
    "wind, water), ONE clear camera movement (slow push-in, tracking, crane, handheld...), lighting/atmosphere changes and "
    "the final beat. Motion-first, never just a static frame. No cuts, no scene changes, no dialogue, no subtitles. "
    "Present tense. Keep characters identical to the keyframe.\n"
    "4) negative: a short image negative. 5) video_negative: LTX negatives focused on bad motion and quality. "
    "6) camera: a short English camera note.\n"
    "Return ONLY a JSON object."
)

COMPILE_SCHEMA = (
    'Return JSON: {"visual_prompt_fa": string, "keyframe_prompt": string, "video_prompt": string, '
    '"negative": string, "video_negative": string, "camera": string}'
)


def _save_prompts(ov: dict, data: dict, text: str | None = None) -> dict:
    key = (data.get("keyframe_prompt") or data.get("visual_prompt") or "").strip()
    vid = (data.get("video_prompt") or "").strip()
    neg = (data.get("negative") or ov.get("negative") or "").strip()
    vneg = (data.get("video_negative") or "").strip() or ", ".join(x for x in (neg, LTX_NEGATIVE) if x)
    ov["keyframe_prompt"] = key
    ov["video_prompt"] = vid
    ov["visual_prompt"] = key  # legacy: old UI/pipeline read this
    ov["negative"] = neg
    ov["video_negative"] = vneg
    if text:
        ov["visual_prompt_fa"] = text
    if data.get("camera"):
        ov["camera"] = data["camera"]
    return ov


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
        + COMPILE_SCHEMA
    )
    llm = get_llm(settings_store.section(db, "llm"))
    raw = await llm.chat([{"role": "system", "content": SYSTEM_COMPILE}, {"role": "user", "content": user}],
                        temperature=0.6, json_mode=True, max_tokens=5000)
    try:
        data = _parse_llm_json(raw)
    except Exception:
        raise HTTPException(502, "LLM returned invalid JSON: " + raw[:500])
    ov = _save_prompts(dict(scene.style_overrides or {}), data,
                       data.get("visual_prompt_fa") or scene.summary or "")
    scene.style_overrides = ov
    db.commit()
    return {"visual_prompt_fa": ov.get("visual_prompt_fa", ""), "keyframe_prompt": ov.get("keyframe_prompt", ""),
            "video_prompt": ov.get("video_prompt", ""), "visual_prompt": ov.get("visual_prompt", ""),
            "negative": ov.get("negative", ""), "video_negative": ov.get("video_negative", ""),
            "camera": ov.get("camera", "")}


SYSTEM_TRANSLATE = (
    "You are a bilingual film-prompt engineer. Rewrite the Persian scene description into TWO English prompts.\n"
    "A) keyframe_prompt for Flux (still image): ONE frozen cinematic frame; shot size, subjects with their English names and "
    "exact wardrobe/appearance, environment, composition, lens, lighting, palette, mood. No camera movement, no motion verbs, "
    "no temporal change, no dialogue. 60-90 words.\n"
    "B) video_prompt for LTX-2.5: ONE flowing paragraph, max 120 words, English. Start directly with the main action. "
    "Then chronological motion and gestures, secondary motion (cloth, hair, dust, wind), ONE clear camera movement, "
    "lighting/atmosphere change and the final beat. Motion-first, never a static description. No cuts, no dialogue, "
    "no on-screen text. Keep characters identical to the keyframe.\n"
    "Also return negative (image) and video_negative (LTX: bad motion and quality). Return ONLY JSON."
)

SYSTEM_TRANSLATE_KEY = (
    "You are a bilingual film-prompt engineer. Rewrite the Persian scene description as ONE English prompt for Flux (still image). "
    "Describe ONE frozen cinematic frame: shot size, subjects with their English names and exact wardrobe/appearance, environment, "
    "composition, lens, lighting, palette, mood. No camera movement, no motion verbs, no temporal change, no dialogue. "
    "60-90 words. Also return a short image negative. Return ONLY JSON."
)

SYSTEM_TRANSLATE_VIDEO = (
    "You are a bilingual film-prompt engineer. Rewrite the Persian scene description as ONE English prompt for LTX-2.5 (video). "
    "Use one flowing paragraph of max 120 words: start directly with the main action, then chronological motion and gestures, "
    "secondary motion (cloth, hair, dust, wind, water), ONE clear camera movement, lighting/atmosphere changes and the final beat. "
    "Motion-first, never a static description. No cuts, no scene changes, no dialogue, no subtitles. Present tense. "
    "Also return LTX negatives focused on bad motion and quality. Return ONLY JSON."
)


@router.post("/api/scenes/{scene_id}/translate-prompt")
async def translate_scene_prompt(scene_id: str, body: TranslateIn, db: Session = Depends(get_db)) -> dict:
    """Rewrite a Persian scene description into a Flux keyframe prompt and/or an LTX video prompt."""
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    project = db.get(Project, scene.script.project_id) if scene.script else None
    ov = dict(scene.style_overrides or {})
    text = (body.text or ov.get("visual_prompt_fa") or scene.summary or scene.action_text or "").strip()
    if not text:
        raise HTTPException(422, "empty prompt")
    target = body.target if body.target in ("both", "keyframe", "video") else "both"
    chars = db.query(Character).filter(Character.project_id == scene.script.project_id).all() if scene.script else []
    names = "\n".join(f"- {c.name} => {c.name_en or c.name}" for c in chars if c.name_en) or "- (none)"
    style = project.style_bible if project else {}
    common = (
        f"Persian scene description:\n{text}\n\n"
        f"Character names (Persian => English):\n{names}\n\n"
        f"Project style: {json.dumps(style, ensure_ascii=False)}\n"
    )
    if target == "keyframe":
        system = SYSTEM_TRANSLATE_KEY
        schema = 'Return JSON: {"keyframe_prompt": string, "negative": string, "camera": string}'
    elif target == "video":
        system = SYSTEM_TRANSLATE_VIDEO
        schema = 'Return JSON: {"video_prompt": string, "video_negative": string, "camera": string}'
    else:
        system = SYSTEM_TRANSLATE
        schema = ('Return JSON: {"keyframe_prompt": string, "video_prompt": string, "negative": string, '
                  '"video_negative": string, "camera": string}')
    llm = get_llm(settings_store.section(db, "llm"))
    raw = await llm.chat([{"role": "system", "content": system}, {"role": "user", "content": common + schema}],
                        temperature=0.4, json_mode=True, max_tokens=3000)
    try:
        data = _parse_llm_json(raw)
    except Exception:
        raise HTTPException(502, "LLM returned invalid JSON: " + raw[:500])
    key = (data.get("keyframe_prompt") or data.get("visual_prompt") or "").strip()
    vid = (data.get("video_prompt") or "").strip()
    if target == "keyframe" and not key:
        raise HTTPException(502, "empty keyframe prompt")
    if target == "video" and not vid:
        raise HTTPException(502, "empty video prompt")
    if target == "both" and (not key or not vid):
        raise HTTPException(502, "empty translation")
    if body.save:
        ov["visual_prompt_fa"] = text
        if key:
            ov["keyframe_prompt"] = key
            ov["visual_prompt"] = key
        if vid:
            ov["video_prompt"] = vid
        if data.get("negative"):
            ov["negative"] = data["negative"]
        if data.get("video_negative"):
            ov["video_negative"] = data["video_negative"]
        elif vid:
            ov["video_negative"] = ", ".join(x for x in (ov.get("negative", ""), LTX_NEGATIVE) if x)
        if data.get("camera"):
            ov["camera"] = data["camera"]
        scene.style_overrides = ov
        db.commit()
    return {"persian": text, "keyframe_prompt": ov.get("keyframe_prompt", ""),
            "video_prompt": ov.get("video_prompt", ""), "english": ov.get("keyframe_prompt", ""),
            "negative": ov.get("negative", ""), "video_negative": ov.get("video_negative", ""),
            "camera": ov.get("camera", "")}


class PromptsIn(BaseModel):
    visual_prompt_fa: str | None = None
    keyframe_prompt: str | None = None
    video_prompt: str | None = None
    negative: str | None = None
    video_negative: str | None = None


@router.post("/api/scenes/{scene_id}/prompts")
def save_scene_prompts(scene_id: str, body: PromptsIn, db: Session = Depends(get_db)) -> dict:
    """Persist manually edited prompts (overwrites only the provided fields)."""
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    ov = dict(scene.style_overrides or {})
    for k in ("visual_prompt_fa", "keyframe_prompt", "video_prompt", "negative", "video_negative"):
        v = getattr(body, k)
        if v is not None:
            ov[k] = v
    if body.keyframe_prompt is not None:
        ov["visual_prompt"] = body.keyframe_prompt
    scene.style_overrides = ov
    db.commit()
    return {"ok": True, "style_overrides": ov}


@router.post("/api/scenes/{scene_id}/look-frame")
async def make_look_frame(scene_id: str, body: LookIn, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    project = db.get(Project, scene.script.project_id) if scene.script else None
    ov = scene.style_overrides or {}
    prompt = ov.get("keyframe_prompt") or body.prompt or ov.get("visual_prompt") or scene_prompt(project, scene, [])
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


@router.post("/api/scenes/{scene_id}/look-frame/inpaint")
async def inpaint_look_frame(scene_id: str, body: LookEditIn, db: Session = Depends(get_db)) -> dict:
    """Mask-based inpainting on the scene's generated first frame (look frame)."""
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    if not scene.look_frame_id:
        raise HTTPException(422, "look frame is not ready")
    base = db.get(Asset, scene.look_frame_id)
    if not base or not Path(base.path).is_file():
        raise HTTPException(422, "look frame asset missing")
    m = re.match(r"^data:image/[a-zA-Z+]+;base64,(.+)$", body.mask, re.S)
    if not m:
        raise HTTPException(422, "mask must be a PNG data URL")
    try:
        mask = base64.b64decode(m.group(1))
    except Exception:
        raise HTTPException(422, "invalid mask")
    project = db.get(Project, scene.script.project_id) if scene.script else None
    ov = scene.style_overrides or {}
    negative = body.negative or ov.get("negative") or (
        (project.style_bible or {}).get("negative") if project else "") or ""
    provider = get_image_provider(settings_store.section(db, "image"))
    seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    raw = await provider.edit(body.prompt, negative, Path(base.path).read_bytes(), mask,
                              seed, body.steps, body.denoise)
    asset = save_asset(db, raw, "image", "png",
                       meta={"scene": scene.id, "kind": "look_frame_inpaint", "prompt": body.prompt,
                             "parent": base.id, "seed": seed})
    scene.look_frame_id = asset.id
    scene.status = "look_ready"
    for shot in db.query(Shot).filter(Shot.scene_id == scene.id, Shot.first_frame_id == base.id):
        shot.first_frame_id = asset.id
    db.commit()
    return {"look_frame_id": asset.id, "url": asset_url(asset.id), "seed": seed,
            "prompt": body.prompt, "parent": base.id}


@router.post("/api/scenes/{scene_id}/shots")
def upsert_shot(scene_id: str, body: ShotIn, db: Session = Depends(get_db)) -> dict:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    prompt, seconds, negative = _shot_defaults(db, scene)
    index = body.index
    if index is None:
        existing = ordered_shots(db, scene_id)
        index = existing[0].index if existing else 1
    shot = db.query(Shot).filter(Shot.scene_id == scene_id, Shot.index == index).first()
    if not shot:
        shot = Shot(scene_id=scene_id, index=index, seconds=seconds)
        db.add(shot)
        db.flush()
    shot.prompt = (body.prompt or "").strip() or shot.prompt or prompt
    shot.negative = negative
    shot.mode = body.mode
    shot.width, shot.height = body.width, body.height
    shot.seconds, shot.fps = body.seconds, body.fps
    shot.seed = body.seed
    shot.generate_audio = body.audio
    if body.first_frame_asset_id:
        shot.first_frame_id = body.first_frame_asset_id
        shot.mode = "i2v"
    elif shot.index == 1 and not shot.first_frame_id and scene.look_frame_id:
        shot.first_frame_id = scene.look_frame_id
    if shot.mode == "auto":
        shot.mode = "i2v" if shot.first_frame_id else "t2v"
    shot.status = "ready"
    cast = db.query(CastMember).filter(CastMember.scene_id == scene_id).all()
    shot.cast_snapshot = [{"character_id": c.character_id, "variant_id": c.variant_id} for c in cast]
    db.commit()
    return shot_public(db, shot)


@router.post("/api/scenes/{scene_id}/shots/apply")
def apply_shots(scene_id: str, body: ShotsApplyIn, db: Session = Depends(get_db)) -> dict:
    """Save an AI-proposed / manually edited shot list for a scene."""
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    if body.replace:
        for shot in ordered_shots(db, scene_id):
            db.delete(shot)
        db.flush()
    existing = {s.index: s for s in ordered_shots(db, scene_id)}
    prompt, seconds, negative = _shot_defaults(db, scene)
    for i, item in enumerate(body.shots, 1):
        try:
            index = max(1, int(item.get("index") or i))
        except Exception:
            index = i
        shot = existing.get(index)
        if not shot:
            shot = Shot(scene_id=scene_id, index=index, seconds=seconds)
            db.add(shot)
            db.flush()
        shot.prompt = (item.get("prompt") or "").strip() or shot.prompt or prompt
        try:
            shot.seconds = float(item.get("seconds") or shot.seconds or seconds)
        except Exception:
            shot.seconds = seconds
        shot.negative = (item.get("negative") or "").strip() or negative
        if shot.index == 1 and not shot.first_frame_id and scene.look_frame_id:
            shot.first_frame_id = scene.look_frame_id
        shot.mode = "i2v" if shot.first_frame_id or shot.index > 1 else "t2v"
        if shot.status == "draft":
            shot.status = "ready"
    renumber(db, scene_id)
    db.commit()
    return scene_detail(db, scene)


SYSTEM_PROPOSE_SHOTS = (
    "You are a film editor and shot designer for the LTX-2.5 video model. "
    "Break ONE screenplay scene into a short, filmable shot list.\n"
    "Rules:\n"
    "- Shot 1 establishes the scene from the scene look frame.\n"
    "- Every following shot must continue naturally from the LAST FRAME of the previous shot "
    "(same characters, wardrobe, location, light and props; no jump cuts inside a shot).\n"
    "- Each prompt is English, motion-first, 40-90 words: start with the main action, then chronological "
    "gestures, secondary motion (cloth, hair, dust, wind, water), ONE clear camera move, and the final beat. "
    "No dialogue, no on-screen text, no cuts, no scene changes.\n"
    "- Vary shot size: wide / medium / close / insert / over_shoulder / pov.\n"
    "- seconds must fit the pacing profile's shot duration and sum close to the scene's planned duration.\n"
    "Return ONLY JSON: {\"shots\": [{\"index\": 1, \"kind\": \"wide\", \"prompt\": \"...\", "
    "\"seconds\": 10, \"camera\": \"slow push-in\"}]}"
)


@router.post("/api/scenes/{scene_id}/propose-shots")
async def propose_shots(scene_id: str, body: ProposeShotsIn, db: Session = Depends(get_db)) -> dict:
    """AI proposal for a scene's shot list; the user can edit it before saving."""
    scene = db.get(Scene, scene_id)
    if not scene:
        raise HTTPException(404, "scene not found")
    ov = scene.style_overrides or {}
    profile = pacing.get_profile(ov.get("pacing_profile") or pacing.DEFAULT_PROFILE)
    scene_seconds = float(ov.get("duration_sec") or sum(profile["scene_duration"]) / 2)
    lo, hi = profile["shots_per_scene"]
    avg_shot = sum(profile["shot_duration"]) / 2
    count = body.count or max(lo, min(hi, int(round(scene_seconds / max(1.0, avg_shot)))))
    count = max(1, min(8, count))

    cast_ids = {c.character_id for c in db.query(CastMember).filter(CastMember.scene_id == scene_id).all()}
    chars = db.query(Character).filter(Character.project_id == scene.script.project_id).all() if scene.script else []
    char_lines = "\n".join(
        f"- {c.name} => {c.name_en or c.name}: {(c.description or '').strip()[:160]}"
        for c in chars if not cast_ids or c.id in cast_ids
    ) or "- none"
    dialogue = "\n".join(f"{d.get('character', '')}: {d.get('line', '')}" for d in (scene.dialogue or []))
    visual = ov.get("video_prompt") or ov.get("keyframe_prompt") or ov.get("visual_prompt") or ""
    user = (
        f"Scene {scene.index}: {scene.heading}\n"
        f"Location: {scene.location} | Time: {scene.time_of_day}\n"
        f"Summary: {scene.summary}\n"
        f"Action: {scene.action_text}\n"
        f"Dialogue:\n{dialogue or '- none'}\n"
        f"Existing visual prompt: {visual or '- none'}\n"
        f"Characters:\n{char_lines}\n\n"
        f"Pacing profile: {profile['label']} ({profile['id']}); scene planned length ~{scene_seconds:.0f}s; "
        f"shot length {profile['shot_duration'][0]}-{profile['shot_duration'][1]}s; "
        f"propose exactly {count} shots.\n"
        "Return the JSON shot list now."
    )
    llm = get_llm(settings_store.section(db, "llm"))
    raw = await llm.chat(
        [{"role": "system", "content": SYSTEM_PROPOSE_SHOTS}, {"role": "user", "content": user}],
        temperature=0.6, json_mode=True, max_tokens=4000,
    )
    try:
        data = _parse_llm_json(raw)
    except Exception:
        raise HTTPException(502, "LLM returned invalid JSON: " + raw[:400])
    items = data.get("shots") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise HTTPException(502, "LLM response has no shot list")
    smin, smax = profile["shot_duration"]
    out = []
    for i, item in enumerate(items[:8], 1):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        try:
            seconds = int(round(float(item.get("seconds") or avg_shot)))
        except Exception:
            seconds = int(round(avg_shot))
        seconds = max(smin, min(smax, seconds))
        out.append({
            "index": len(out) + 1,
            "kind": str(item.get("kind") or "medium"),
            "prompt": prompt,
            "seconds": seconds,
            "camera": str(item.get("camera") or ""),
        })
    if not out:
        raise HTTPException(502, "LLM returned no usable shots")
    return {"data": out, "profile": profile["id"], "scene_seconds": scene_seconds, "count": len(out)}


@router.delete("/api/shots/{shot_id}")
def delete_shot(shot_id: str, db: Session = Depends(get_db)) -> dict:
    shot = db.get(Shot, shot_id)
    if not shot:
        raise HTTPException(404, "shot not found")
    scene_id = shot.scene_id
    db.delete(shot)
    db.flush()
    renumber(db, scene_id)
    db.commit()
    scene = db.get(Scene, scene_id)
    return scene_detail(db, scene) if scene else {"ok": True}


@router.post("/api/shots/{shot_id}/chain")
async def chain_shot_from_previous(shot_id: str, db: Session = Depends(get_db)) -> dict:
    """Use the last frame of the previous shot in the same scene as this shot's first frame."""
    shot = db.get(Shot, shot_id)
    if not shot:
        raise HTTPException(404, "shot not found")
    try:
        frame = await chain_from_previous(db, shot)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    return {"shot_id": shot.id, "first_frame_id": frame.id, "url": asset_url(frame.id)}


@router.post("/api/shots/{shot_id}/first-frame/inpaint")
async def inpaint_shot_first_frame(shot_id: str, body: ShotFirstFrameInpaintIn,
                                   db: Session = Depends(get_db)) -> dict:
    """Mask-based edit of a shot's first frame (chained frame or look frame)."""
    shot = db.get(Shot, shot_id)
    if not shot:
        raise HTTPException(404, "shot not found")
    if not shot.first_frame_id:
        raise HTTPException(422, "shot has no first frame yet")
    base = db.get(Asset, shot.first_frame_id)
    if not base or not Path(base.path).is_file():
        raise HTTPException(422, "first frame asset missing")
    m = re.match(r"^data:image/[a-zA-Z+]+;base64,(.+)$", body.mask, re.S)
    if not m:
        raise HTTPException(422, "mask must be a PNG data URL")
    try:
        mask = base64.b64decode(m.group(1))
    except Exception:
        raise HTTPException(422, "invalid mask")
    scene = db.get(Scene, shot.scene_id)
    ov = (scene.style_overrides if scene else {}) or {}
    negative = body.negative or ov.get("negative") or ""
    provider = get_image_provider(settings_store.section(db, "image"))
    seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    raw = await provider.edit(body.prompt, negative, Path(base.path).read_bytes(), mask,
                              seed, body.steps, body.denoise)
    asset = save_asset(db, raw, "image", "png",
                       meta={"kind": MANUAL_FRAME_KIND, "shot": shot.id, "parent": base.id,
                             "prompt": body.prompt, "seed": seed})
    shot.first_frame_id = asset.id
    shot.mode = "i2v"
    shot.status = "ready"
    db.commit()
    return {"shot_id": shot.id, "first_frame_id": asset.id, "url": asset_url(asset.id), "seed": seed}


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
    shot = db.query(Shot).filter(Shot.scene_id == prev.id).order_by(Shot.index.desc()).first()
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
