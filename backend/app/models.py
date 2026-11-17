"""Studio data model.

Everything is scoped to a Project. Characters are reusable across scenes and
carry canonical reference images plus wardrobe variants and a voice profile.
Scripts are a list of scenes; scenes cast characters and are rendered as shots.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[float] = mapped_column(Float, default=now)
    updated_at: Mapped[float] = mapped_column(Float, default=now, onupdate=now)


class Project(Base, Timestamped):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="fa")
    pacing_profile: Mapped[str] = mapped_column(String(40), default="epic_historical")
    target_duration_sec: Mapped[int] = mapped_column(Integer, default=600)
    style_bible: Mapped[dict] = mapped_column(JSON, default=dict)

    characters: Mapped[list["Character"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scripts: Mapped[list["Script"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Asset(Base, Timestamped):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(80), default="application/octet-stream")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Character(Base, Timestamped):
    __tablename__ = "characters"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[dict] = mapped_column(JSON, default=dict)
    negative: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_image_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="characters")
    images: Mapped[list["CharacterImage"]] = relationship(back_populates="character", cascade="all, delete-orphan")
    variants: Mapped[list["WardrobeVariant"]] = relationship(back_populates="character", cascade="all, delete-orphan")
    voice: Mapped["VoiceProfile | None"] = relationship(back_populates="character", uselist=False, cascade="all, delete-orphan")


class CharacterImage(Base, Timestamped):
    __tablename__ = "character_images"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    kind: Mapped[str] = mapped_column(String(32), default="portrait")
    prompt: Mapped[str] = mapped_column(Text, default="")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    character: Mapped["Character"] = relationship(back_populates="images")


class WardrobeVariant(Base, Timestamped):
    __tablename__ = "wardrobe_variants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prompt_delta: Mapped[str] = mapped_column(Text, default="")
    reference_image_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)

    character: Mapped["Character"] = relationship(back_populates="variants")


class VoiceProfile(Base, Timestamped):
    __tablename__ = "voice_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(40), default="piper")
    voice_id: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(16), default="fa")
    reference_audio_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    sample_audio_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    character: Mapped["Character"] = relationship(back_populates="voice")


class Script(Base, Timestamped):
    __tablename__ = "scripts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    logline: Mapped[str] = mapped_column(Text, default="")
    treatment: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="draft")
    source: Mapped[str] = mapped_column(String(16), default="ai")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped["Project"] = relationship(back_populates="scripts")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="script", cascade="all, delete-orphan", order_by="Scene.index")


class Scene(Base, Timestamped):
    __tablename__ = "scenes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    heading: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    time_of_day: Mapped[str] = mapped_column(String(60), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    action_text: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[list] = mapped_column(JSON, default=list)
    style_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_scene_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    look_frame_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")

    script: Mapped["Script"] = relationship(back_populates="scenes")
    cast: Mapped[list["CastMember"]] = relationship(back_populates="scene", cascade="all, delete-orphan")
    shots: Mapped[list["Shot"]] = relationship(back_populates="scene", cascade="all, delete-orphan", order_by="Shot.index")


class CastMember(Base, Timestamped):
    __tablename__ = "cast_members"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"))
    variant_id: Mapped[str | None] = mapped_column(ForeignKey("wardrobe_variants.id"), nullable=True)
    role_in_scene: Mapped[str] = mapped_column(String(120), default="")
    prompt_delta: Mapped[str] = mapped_column(Text, default="")
    reference_image_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)

    scene: Mapped["Scene"] = relationship(back_populates="cast")


class Shot(Base, Timestamped):
    __tablename__ = "shots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    prompt: Mapped[str] = mapped_column(Text, default="")
    negative: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="t2v")
    width: Mapped[int] = mapped_column(Integer, default=1280)
    height: Mapped[int] = mapped_column(Integer, default=720)
    fps: Mapped[float] = mapped_column(Float, default=24.0)
    seconds: Mapped[float] = mapped_column(Float, default=4.0)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generate_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    first_frame_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    last_frame_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    cast_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="draft")

    scene: Mapped["Scene"] = relationship(back_populates="shots")
    renders: Mapped[list["Render"]] = relationship(back_populates="shot", cascade="all, delete-orphan")


class Render(Base, Timestamped):
    __tablename__ = "renders"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="ltx-2.5")
    provider_job_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="queued")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    video_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    audio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")

    shot: Mapped["Shot"] = relationship(back_populates="renders")


class AppSetting(Base, Timestamped):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
