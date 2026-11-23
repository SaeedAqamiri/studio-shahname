from __future__ import annotations

import base64
import random
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import get_db
from ..models import Asset, Render, Scene, Shot
from ..providers import get_video_api
from ..services.assets import asset_url, save_asset
from ..services.shots import auto_chain_next, ensure_first_frame

router = APIRouter(tags=["renders"])


class RenderIn(BaseModel):
    prompt: str | None = None
    seed: int | None = None
    seconds: float | None = None
    audio: bool | None = None
    first_frame_asset_id: str | None = None


def render_public(db: Session, r: Render, shot: Shot | None = None) -> dict:
    shot = shot or db.get(Shot, r.shot_id)
    scene = db.get(Scene, shot.scene_id) if shot else None
    return {
        "id": r.id, "shot_id": r.shot_id, "scene_id": shot.scene_id if shot else None,
        "scene_heading": scene.heading if scene else "", "scene_index": scene.index if scene else None,
        "provider": r.provider, "status": r.status, "error": r.error,
        "video_asset_id": r.video_asset_id, "video_url": asset_url(r.video_asset_id),
        "params": r.params, "created_at": r.created_at,
        "prompt": (shot.prompt if shot else ""),
    }


@router.post("/api/shots/{shot_id}/render")
async def start_render(shot_id: str, body: RenderIn, db: Session = Depends(get_db)) -> dict:
    shot = db.get(Shot, shot_id)
    if not shot:
        raise HTTPException(404, "shot not found")
    cfg = settings_store.section(db, "video")
    api = get_video_api(cfg)
    prompt = body.prompt or shot.prompt
    if not prompt:
        raise HTTPException(422, "empty prompt")
    seed = body.seed if body.seed is not None else (shot.seed if shot.seed is not None else random.randint(1, 2**31 - 1))
    seconds = body.seconds or shot.seconds
    audio = shot.generate_audio if body.audio is None else body.audio
    if body.first_frame_asset_id:
        shot.first_frame_id = body.first_frame_asset_id
        shot.mode = "i2v"
    try:
        first_frame_id = await ensure_first_frame(db, shot)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    first_frame = None
    if first_frame_id:
        a = db.get(Asset, first_frame_id)
        if not a or not Path(a.path).is_file():
            raise HTTPException(422, "first frame not found")
        mime = "image/png"
        raw = Path(a.path).read_bytes()
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        first_frame = f"data:{mime};base64," + base64.b64encode(raw).decode()

    payload = {
        "model": cfg.get("model") or "ltx-2.5",
        "prompt": prompt,
        "negative": shot.negative,
        "size": f"{shot.width}x{shot.height}",
        "seconds": float(seconds),
        "fps": float(shot.fps),
        "seed": int(seed),
        "audio": bool(audio),
    }
    if first_frame:
        payload["first_frame"] = first_frame
    job = await api.submit(payload)
    r = Render(shot_id=shot.id, provider="ltx-2.5", provider_job_id=job["id"], status=job.get("status", "queued"),
               params={"seed": seed, "seconds": seconds, "size": payload["size"], "mode": "i2v" if first_frame else "t2v",
                       "audio": audio, "provider_job": job["id"]})
    db.add(r)
    shot.status = "rendering"
    db.commit()
    return render_public(db, r, shot)


@router.get("/api/renders")
def list_renders(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    rows = db.query(Render).order_by(Render.created_at.desc()).limit(max(1, min(limit, 200))).all()
    return {"data": [render_public(db, r) for r in rows]}


@router.get("/api/renders/{render_id}")
async def get_render(render_id: str, db: Session = Depends(get_db)) -> dict:
    r = db.get(Render, render_id)
    if not r:
        raise HTTPException(404, "render not found")
    if r.status in ("queued", "running") and r.provider_job_id:
        cfg = settings_store.section(db, "video")
        api = get_video_api(cfg)
        try:
            j = await api.get(r.provider_job_id)
        except Exception as exc:  # noqa: BLE001
            return render_public(db, r)
        st = j.get("status")
        if st and st != r.status:
            r.status = st
        if st == "succeeded" and not r.video_asset_id:
            raw = await api.content(r.provider_job_id)
            asset = save_asset(db, raw, "video", "mp4", mime="video/mp4",
                               meta={"render": r.id, "prompt": (db.get(Shot, r.shot_id).prompt if db.get(Shot, r.shot_id) else ""),
                                     "params": r.params})
            r.video_asset_id = asset.id
            shot = db.get(Shot, r.shot_id)
            if shot:
                shot.status = "done"
                try:
                    await auto_chain_next(db, shot, r)
                except Exception:
                    pass
        if st == "failed":
            r.error = j.get("error") or "failed"
            shot = db.get(Shot, r.shot_id)
            if shot:
                shot.status = "failed"
        db.commit()
    return render_public(db, r)


@router.post("/api/renders/{render_id}/cancel")
async def cancel_render(render_id: str, db: Session = Depends(get_db)) -> dict:
    r = db.get(Render, render_id)
    if not r:
        raise HTTPException(404, "render not found")
    cfg = settings_store.section(db, "video")
    try:
        await get_video_api(cfg).cancel(r.provider_job_id)
    except Exception:
        pass
    r.status = "cancelled"
    db.commit()
    return render_public(db, r)
