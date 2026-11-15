from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Asset, Project, Render, Scene, Script, Shot
from ..services.prompting import style_bible
from ..services.assets import asset_url, save_asset
from ..services.video import concat, probe
from ..services.audio import dub_video, duration as media_duration
from .scenes import build_narration
from .. import config

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    language: str = "fa"
    style_bible: dict = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    language: str | None = None
    style_bible: dict | None = None


def project_public(p: Project) -> dict:
    return {
        "id": p.id, "name": p.name, "description": p.description, "language": p.language,
        "style_bible": p.style_bible, "created_at": p.created_at, "updated_at": p.updated_at,
    }


@router.get("")
def list_projects(db: Session = Depends(get_db)) -> dict:
    rows = db.query(Project).order_by(Project.created_at.desc()).all()
    return {"data": [project_public(p) for p in rows]}


@router.post("")
def create_project(body: ProjectIn, db: Session = Depends(get_db)) -> dict:
    p = Project(name=body.name, description=body.description, language=body.language,
                style_bible=body.style_bible or style_bible(None))
    db.add(p)
    db.commit()
    return project_public(p)


@router.get("/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)) -> dict:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    return project_public(p)


@router.patch("/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, db: Session = Depends(get_db)) -> dict:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return project_public(p)


class EditIn(BaseModel):
    script_id: str | None = None


@router.post("/{project_id}/edit")
async def final_cut(project_id: str, body: EditIn, db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    script = db.get(Script, body.script_id) if body.script_id else (
        db.query(Script).filter(Script.project_id == project_id).order_by(Script.created_at.desc()).first())
    if not script:
        raise HTTPException(404, "script not found")
    scenes = db.query(Scene).filter(Scene.script_id == script.id).order_by(Scene.index).all()
    clips = []
    used = []
    for sc in scenes:
        shot = db.query(Shot).filter(Shot.scene_id == sc.id).order_by(Shot.index).first()
        if not shot:
            continue
        render = (db.query(Render).filter(Render.shot_id == shot.id, Render.status == "succeeded",
                                          Render.video_asset_id.isnot(None))
                  .order_by(Render.created_at.desc()).first())
        if not render:
            continue
        asset = db.get(Asset, render.video_asset_id)
        if asset and Path(asset.path).is_file():
            clips.append(asset.path)
            used.append(sc.index)
    if not clips:
        raise HTTPException(422, "no finished renders to edit")
    out = config.ASSETS / f"final_{project_id}_{int(__import__('time').time())}.mp4"
    info = await concat(clips, str(out))
    asset = save_asset(db, out.read_bytes(), "video", "mp4", mime="video/mp4",
                       meta={"kind": "final_cut", "project": project_id, "script": script.id, "scenes": used, **info})
    db.commit()
    return {"asset_id": asset.id, "url": asset_url(asset.id), "scenes": used, **info}


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@router.post("/{project_id}/export")
async def export_av(project_id: str, body: EditIn, db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "project not found")
    script = db.get(Script, body.script_id) if body.script_id else (
        db.query(Script).filter(Script.project_id == project_id).order_by(Script.created_at.desc()).first())
    if not script:
        raise HTTPException(404, "script not found")
    scenes = db.query(Scene).filter(Scene.script_id == script.id).order_by(Scene.index).all()
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="export_"))
    clips, used = [], []
    for sc in scenes:
        shot = db.query(Shot).filter(Shot.scene_id == sc.id).order_by(Shot.index).first()
        if not shot:
            continue
        render = (db.query(Render).filter(Render.shot_id == shot.id, Render.status == "succeeded",
                                          Render.video_asset_id.isnot(None))
                  .order_by(Render.created_at.desc()).first())
        if not render:
            continue
        asset = db.get(Asset, render.video_asset_id)
        if not asset or not Path(asset.path).is_file():
            continue
        clip = asset.path
        narration, lines = await build_narration(db, sc)
        if narration:
            out = str(tmp / f"scene_{sc.index}.mp4")
            await dub_video(clip, narration, out)
            clip = out
        clips.append(clip)
        used.append(sc)
    if not clips:
        raise HTTPException(422, "no finished renders")

    final = str(tmp / "final.mp4")
    await concat(clips, final)

    entries = []
    t = 0.0
    for sc, clip in zip(used, clips):
        dur = await media_duration(clip) or 4.0
        dialogue = [d for d in (sc.dialogue or []) if (d.get("line") or "").strip()]
        if dialogue:
            weights = [max(1, len(d["line"])) for d in dialogue]
            total = sum(weights)
            cur = t
            for d, w in zip(dialogue, weights):
                seg = dur * (w / total)
                name = d.get("character") or ""
                entries.append((cur + 0.1, min(t + dur, cur + seg - 0.05), f"{name}: {d['line']}".strip(": ")))
                cur += seg
        t += dur
    srt = "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt}\n" for i, (a, b, txt) in enumerate(entries, 1))

    rad = Path(final).read_bytes()
    video_asset = save_asset(db, rad, "video", "mp4", mime="video/mp4",
                             meta={"kind": "export_av", "project": project_id, "script": script.id,
                                   "scenes": [sc.index for sc in used]})
    srt_asset = None
    if srt.strip():
        srt_asset = save_asset(db, srt.encode("utf-8"), "text", "srt", mime="application/x-subrip",
                               meta={"kind": "export_srt", "project": project_id, "script": script.id})
    db.commit()
    return {"video_url": asset_url(video_asset.id), "video_asset_id": video_asset.id,
            "srt_url": asset_url(srt_asset.id) if srt_asset else None,
            "srt": srt, "scenes": [sc.index for sc in used]}
