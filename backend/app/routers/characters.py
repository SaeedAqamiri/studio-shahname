from __future__ import annotations

import asyncio
import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Character, CharacterImage, Project, WardrobeVariant
from .. import settings_store
from ..providers import get_image_provider
from ..services.assets import asset_url, save_asset
from ..services.prompting import character_negative, character_prompt

router = APIRouter(tags=["characters"])


class CharacterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    name_en: str = ""
    role: str = ""
    description: str = ""
    appearance: dict = Field(default_factory=dict)
    negative: str = ""
    seed: int | None = None


class CharacterPatch(BaseModel):
    name: str | None = None
    name_en: str | None = None
    role: str | None = None
    description: str | None = None
    appearance: dict | None = None
    negative: str | None = None
    seed: int | None = None


class GenerateIn(BaseModel):
    count: int = Field(default=4, ge=1, le=6)
    width: int = Field(default=832, ge=384, le=1536)
    height: int = Field(default=1216, ge=384, le=1536)
    extra_prompt: str = ""
    framing: str = "portrait"  # portrait | full | turnaround
    seed: int | None = None
    reference_image_id: str | None = None


class CanonicalIn(BaseModel):
    image_id: str


class VariantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt_delta: str = ""
    reference_image_id: str | None = None


def image_public(db: Session, img: CharacterImage) -> dict:
    return {
        "id": img.id,
        "asset_id": img.asset_id,
        "url": asset_url(img.asset_id),
        "kind": img.kind,
        "prompt": img.prompt,
        "seed": img.seed,
        "parent_id": img.parent_id,
        "created_at": img.created_at,
    }


def character_public(db: Session, c: Character) -> dict:
    images = db.query(CharacterImage).filter(CharacterImage.character_id == c.id).order_by(CharacterImage.created_at.desc()).all()
    variants = db.query(WardrobeVariant).filter(WardrobeVariant.character_id == c.id).all()
    return {
        "id": c.id,
        "project_id": c.project_id,
        "name": c.name,
        "name_en": c.name_en,
        "role": c.role,
        "description": c.description,
        "appearance": c.appearance,
        "negative": c.negative,
        "seed": c.seed,
        "canonical_image_id": c.canonical_image_id,
        "canonical_url": asset_url(c.canonical_image_id),
        "images": [image_public(db, i) for i in images],
        "variants": [
            {"id": v.id, "name": v.name, "prompt_delta": v.prompt_delta,
             "reference_image_id": v.reference_image_id, "reference_url": asset_url(v.reference_image_id)}
            for v in variants
        ],
        "voice": {
            "provider": c.voice.provider, "voice_id": c.voice.voice_id, "language": c.voice.language,
            "settings": c.voice.settings, "reference_audio_id": c.voice.reference_audio_id,
            "reference_url": asset_url(c.voice.reference_audio_id),
        } if c.voice else None,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("/api/projects/{project_id}/characters")
def list_characters(project_id: str, db: Session = Depends(get_db)) -> dict:
    rows = db.query(Character).filter(Character.project_id == project_id).order_by(Character.created_at).all()
    return {"data": [character_public(db, c) for c in rows]}


@router.post("/api/projects/{project_id}/characters")
def create_character(project_id: str, body: CharacterIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    c = Character(project_id=project_id, **body.model_dump())
    db.add(c)
    db.commit()
    return character_public(db, c)


@router.get("/api/characters/{character_id}")
def get_character(character_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    return character_public(db, c)


@router.patch("/api/characters/{character_id}")
def patch_character(character_id: str, body: CharacterPatch, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    db.commit()
    return character_public(db, c)


@router.delete("/api/characters/{character_id}")
def delete_character(character_id: str, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    db.delete(c)
    db.commit()
    return {"deleted": True}


@router.post("/api/characters/{character_id}/generate")
async def generate_images(character_id: str, body: GenerateIn, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    if not c:
        raise HTTPException(404, "character not found")
    project = db.get(Project, c.project_id)
    prompt = character_prompt(project, c, body.extra_prompt, body.framing)
    negative = character_negative(project, c)

    refs: list[bytes] = []
    if body.reference_image_id:
        asset = db.get(Asset, body.reference_image_id)
        if not asset or not Path(asset.path).is_file():
            raise HTTPException(422, "reference image not found")
        refs = [Path(asset.path).read_bytes()]

    provider = get_image_provider(settings_store.section(db, "image"))
    base_seed = body.seed if body.seed is not None else random.randint(1, 2**31 - 1)
    seeds = [base_seed + i for i in range(body.count)]

    async def one(seed: int) -> tuple[bytes, int]:
        return await provider.generate(prompt, negative, body.width, body.height, seed, refs or None), seed

    results = await asyncio.gather(*[one(s) for s in seeds], return_exceptions=True)
    created = []
    errors = []
    for item in results:
        if isinstance(item, Exception):
            errors.append(str(item)[:300])
            continue
        raw, seed = item
        asset = save_asset(db, raw, "image", "png", meta={"prompt": prompt, "seed": seed, "character": c.id})
        img = CharacterImage(character_id=c.id, asset_id=asset.id, kind=body.framing, prompt=prompt,
                             seed=seed, parent_id=body.reference_image_id)
        db.add(img)
        db.flush()
        if not c.canonical_image_id:
            c.canonical_image_id = asset.id
        created.append(image_public(db, img))
    if not created and errors:
        raise HTTPException(502, "image generation failed: " + errors[0])
    db.commit()
    return {"images": created, "errors": errors, "prompt": prompt, "negative": negative, "seed": base_seed}


@router.post("/api/characters/{character_id}/canonical")
def set_canonical(character_id: str, body: CanonicalIn, db: Session = Depends(get_db)) -> dict:
    c = db.get(Character, character_id)
    img = db.get(CharacterImage, body.image_id)
    if not c or not img or img.character_id != c.id:
        raise HTTPException(404, "not found")
    c.canonical_image_id = img.asset_id
    db.commit()
    return character_public(db, c)


@router.post("/api/characters/{character_id}/variants")
def add_variant(character_id: str, body: VariantIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Character, character_id):
        raise HTTPException(404, "character not found")
    v = WardrobeVariant(character_id=character_id, **body.model_dump())
    db.add(v)
    db.commit()
    return {"id": v.id, "name": v.name, "prompt_delta": v.prompt_delta,
            "reference_image_id": v.reference_image_id, "reference_url": asset_url(v.reference_image_id)}


@router.delete("/api/characters/{character_id}/variants/{variant_id}")
def delete_variant(character_id: str, variant_id: str, db: Session = Depends(get_db)) -> dict:
    v = db.get(WardrobeVariant, variant_id)
    if not v or v.character_id != character_id:
        raise HTTPException(404, "not found")
    db.delete(v)
    db.commit()
    return {"deleted": True}
