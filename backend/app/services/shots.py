"""Shot-level helpers shared by the scenes and renders routers.

A scene (screenplay beat) can be rendered as several shots.  The first shot
always starts from the scene look frame; every following shot starts from the
last frame of the previous shot (true i2v continuity) unless the user painted
a manual first frame with the inpainting tool.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import Asset, Render, Scene, Shot
from .assets import save_asset
from .video import extract_frame

MANUAL_FRAME_KIND = "shot_first_frame_inpaint"


def ordered_shots(db: Session, scene_id: str) -> list[Shot]:
    return db.query(Shot).filter(Shot.scene_id == scene_id).order_by(Shot.index).all()


def renumber(db: Session, scene_id: str) -> None:
    for i, shot in enumerate(ordered_shots(db, scene_id), 1):
        shot.index = i
    db.flush()


def is_manual_first_frame(db: Session, shot: Shot) -> bool:
    if not shot.first_frame_id:
        return False
    asset = db.get(Asset, shot.first_frame_id)
    return bool(asset and (asset.meta or {}).get("kind") == MANUAL_FRAME_KIND)


def previous_shot(db: Session, shot: Shot) -> Shot | None:
    return (
        db.query(Shot)
        .filter(Shot.scene_id == shot.scene_id, Shot.index < shot.index)
        .order_by(Shot.index.desc())
        .first()
    )


def last_succeeded_render(db: Session, shot: Shot) -> Render | None:
    return (
        db.query(Render)
        .filter(Render.shot_id == shot.id, Render.status == "succeeded", Render.video_asset_id.isnot(None))
        .order_by(Render.created_at.desc())
        .first()
    )


async def chain_from_render(db: Session, shot: Shot, render: Render) -> Asset:
    """Set a shot's first frame to the last frame of the given finished render."""
    asset = db.get(Asset, render.video_asset_id) if render.video_asset_id else None
    if not asset or not Path(asset.path).is_file():
        raise ValueError("previous video asset missing")
    out = config.ASSETS / f"chain_{shot.id}_{render.id}.png"
    await extract_frame(asset.path, str(out), last=True)
    frame = save_asset(
        db, out.read_bytes(), "image", "png",
        meta={"kind": "chain_frame", "shot": shot.id, "from_render": render.id},
    )
    shot.first_frame_id = frame.id
    shot.mode = "i2v"
    if shot.status == "draft":
        shot.status = "ready"
    db.flush()
    return frame


async def chain_from_previous(db: Session, shot: Shot) -> Asset:
    prev = previous_shot(db, shot)
    if not prev:
        raise ValueError("no previous shot in this scene")
    render = last_succeeded_render(db, prev)
    if not render:
        raise ValueError("previous shot has no finished render")
    return await chain_from_render(db, shot, render)


async def auto_chain_next(db: Session, shot: Shot, render: Render) -> Shot | None:
    """After a shot finishes, refresh the next shot's first frame unless the
    user edited it manually."""
    nxt = (
        db.query(Shot)
        .filter(Shot.scene_id == shot.scene_id, Shot.index == shot.index + 1)
        .first()
    )
    if not nxt or is_manual_first_frame(db, nxt):
        return None
    await chain_from_render(db, nxt, render)
    return nxt


async def ensure_first_frame(db: Session, shot: Shot) -> str:
    """Guarantee a first frame: look frame for shot 1, chained frame afterwards."""
    if shot.first_frame_id:
        asset = db.get(Asset, shot.first_frame_id)
        if asset and Path(asset.path).is_file():
            return shot.first_frame_id
        shot.first_frame_id = None

    if shot.index <= 1:
        scene = db.get(Scene, shot.scene_id)
        if not scene or not scene.look_frame_id:
            raise ValueError("first shot needs the scene look frame; generate it first")
        look = db.get(Asset, scene.look_frame_id)
        if not look or not Path(look.path).is_file():
            raise ValueError("scene look frame file is missing; regenerate it")
        shot.first_frame_id = scene.look_frame_id
        shot.mode = "i2v"
        db.flush()
        return shot.first_frame_id

    await chain_from_previous(db, shot)
    return shot.first_frame_id
