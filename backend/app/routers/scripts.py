from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import settings_store
from ..db import get_db
from ..models import Asset, Character, Project, Render, Scene, Script, Shot
from ..providers import get_llm
from ..services import pacing
from ..services.assets import asset_url, save_asset
from ..services.video import probe
from .. import config

router = APIRouter(tags=["scripts"])


class ScriptIn(BaseModel):
    title: str = ""
    logline: str = ""
    treatment: str = ""
    source: str = "user"


class ScriptPatch(BaseModel):
    title: str | None = None
    logline: str | None = None
    treatment: str | None = None
    status: str | None = None
    meta: dict | None = None


class ScenePatch(BaseModel):
    index: int | None = None
    heading: str | None = None
    location: str | None = None
    time_of_day: str | None = None
    summary: str | None = None
    action_text: str | None = None
    dialogue: list | None = None
    style_overrides: dict | None = None
    status: str | None = None


class SceneIn(BaseModel):
    heading: str = ""
    location: str = ""
    time_of_day: str = ""
    summary: str = ""
    action_text: str = ""
    dialogue: list = Field(default_factory=list)


class GenerateIn(BaseModel):
    treatment: str | None = None
    scene_count: int = Field(default=6, ge=1, le=30)
    language: str = "fa"
    tone: str = ""
    replace: bool = True


def scene_public(s: Scene) -> dict:
    return {
        "id": s.id, "script_id": s.script_id, "index": s.index, "heading": s.heading,
        "location": s.location, "time_of_day": s.time_of_day, "summary": s.summary,
        "action_text": s.action_text, "dialogue": s.dialogue or [],
        "style_overrides": s.style_overrides or {}, "prev_scene_id": s.prev_scene_id,
        "status": s.status, "look_frame_id": s.look_frame_id,
    }


def script_public(db: Session, s: Script, with_scenes: bool = True) -> dict:
    out = {
        "id": s.id, "project_id": s.project_id, "title": s.title, "logline": s.logline,
        "treatment": s.treatment, "status": s.status, "source": s.source, "meta": s.meta or {},
        "created_at": s.created_at, "updated_at": s.updated_at,
    }
    if with_scenes:
        scenes = db.query(Scene).filter(Scene.script_id == s.id).order_by(Scene.index).all()
        out["scenes"] = [scene_public(x) for x in scenes]
    return out


@router.get("/api/projects/{project_id}/scripts")
def list_scripts(project_id: str, db: Session = Depends(get_db)) -> dict:
    rows = db.query(Script).filter(Script.project_id == project_id).order_by(Script.created_at.desc()).all()
    return {"data": [script_public(db, s, with_scenes=False) for s in rows]}


@router.post("/api/projects/{project_id}/scripts")
def create_script(project_id: str, body: ScriptIn, db: Session = Depends(get_db)) -> dict:
    if not db.get(Project, project_id):
        raise HTTPException(404, "project not found")
    s = Script(project_id=project_id, **body.model_dump())
    db.add(s)
    db.commit()
    return script_public(db, s)


@router.get("/api/scripts/{script_id}")
def get_script(script_id: str, db: Session = Depends(get_db)) -> dict:
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "script not found")
    return script_public(db, s)


@router.patch("/api/scripts/{script_id}")
def patch_script(script_id: str, body: ScriptPatch, db: Session = Depends(get_db)) -> dict:
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "script not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    return script_public(db, s)


@router.delete("/api/scripts/{script_id}")
def delete_script(script_id: str, db: Session = Depends(get_db)) -> dict:
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "script not found")
    db.delete(s)
    db.commit()
    return {"deleted": True}


@router.post("/api/scripts/{script_id}/scenes")
def add_scene(script_id: str, body: SceneIn, db: Session = Depends(get_db)) -> dict:
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "script not found")
    last = db.query(Scene).filter(Scene.script_id == script_id).order_by(Scene.index.desc()).first()
    scene = Scene(script_id=script_id, index=(last.index + 1 if last else 1),
                  prev_scene_id=(last.id if last else None), **body.model_dump())
    db.add(scene)
    db.commit()
    return scene_public(scene)


@router.patch("/api/scenes/{scene_id}")
def patch_scene(scene_id: str, body: ScenePatch, db: Session = Depends(get_db)) -> dict:
    s = db.get(Scene, scene_id)
    if not s:
        raise HTTPException(404, "scene not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    return scene_public(s)


@router.delete("/api/scenes/{scene_id}")
def delete_scene(scene_id: str, db: Session = Depends(get_db)) -> dict:
    s = db.get(Scene, scene_id)
    if not s:
        raise HTTPException(404, "scene not found")
    db.delete(s)
    db.commit()
    return {"deleted": True}


SYSTEM = (
    "You are a professional screenwriter for a cinematic film and animation studio. "
    "Write in Persian unless asked otherwise. Return ONLY valid JSON, no markdown. "
    "Respect the project's format, genre, pacing profile and target duration. "
    "Each scene must be visually filmable: concrete place, time, action, camera mood. "
    "Keep characters consistent with the provided list. Do not assume the project is Shahnameh unless the brief says so."
)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


@router.post("/api/scripts/{script_id}/generate")
async def generate_script(script_id: str, body: GenerateIn, db: Session = Depends(get_db)) -> dict:
    s = db.get(Script, script_id)
    if not s:
        raise HTTPException(404, "script not found")
    project = db.get(Project, s.project_id)
    chars = db.query(Character).filter(Character.project_id == s.project_id).all()
    treatment = body.treatment or s.treatment
    if not treatment.strip():
        raise HTTPException(422, "treatment is empty")

    profile = pacing.get_profile(project.pacing_profile if project else None)
    target = project.target_duration_sec if project else 600
    style = project.style_bible if project else {}
    char_lines = "\n".join(f"- {c.name} ({c.role or 'character'}): {c.description[:160]}" for c in chars) or "- (none yet)"
    n = body.scene_count
    dmin, dmax = profile["scene_duration"]
    if n < profile["scene_count"][0] and target > dmax * n:
        n = pacing.scene_count_suggestion(target, profile["id"])
    brief = pacing.pacing_brief(profile["id"], target)
    user = (
        f"Project: {project.name if project else ''}\n"
        f"Project style: {json.dumps(style, ensure_ascii=False)}\n"
        f"Pacing brief: {brief}\n"
        f"Characters:\n{char_lines}\n\n"
        f"Treatment / outline:\n{treatment}\n\n"
        f"Tone: {body.tone or 'cinematic, grounded'}\n"
        f"Write exactly {n} scenes. Each scene duration must be {dmin}-{dmax} seconds; "
        f"total close to {target} seconds. Use {profile['shots_per_scene'][0]}-{profile['shots_per_scene'][1]} "
        f"shots per scene, each {profile['shot_duration'][0]}-{profile['shot_duration'][1]} seconds. "
        "Return JSON with this exact schema:\n"
        '{"title": string, "logline": string, "scenes": [{"heading": string, "location": string, '
        '"time_of_day": string, "summary": string, "action_text": string, "duration_sec": integer, '
        '"dialogue": [{"character": string, "line": string, "emotion": string}], '
        '"cast": [string]}]}'
    )
    llm = get_llm(settings_store.section(db, "llm"))
    raw = await llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                        temperature=0.8, json_mode=True, max_tokens=6000)
    try:
        data = _parse_json(raw)
    except Exception:
        raise HTTPException(502, "LLM returned invalid JSON: " + raw[:300])

    if body.replace:
        db.query(Scene).filter(Scene.script_id == script_id).delete()
    s.treatment = treatment
    if data.get("title"):
        s.title = data["title"]
    if data.get("logline"):
        s.logline = data["logline"]
    s.source = "ai"
    s.status = "draft"
    scenes = data.get("scenes") or []
    start = 0 if body.replace else db.query(Scene).filter(Scene.script_id == script_id).count()
    prev = None if body.replace else db.query(Scene).filter(Scene.script_id == script_id).order_by(Scene.index.desc()).first()
    prev_id = prev.id if prev else None
    avg = (dmin + dmax) / 2
    for i, sc in enumerate(scenes):
        try:
            dur = int(round(float(sc.get("duration_sec") or avg)))
        except Exception:
            dur = int(round(avg))
        dur = max(dmin, min(dmax, dur))
        row = Scene(
            script_id=script_id, index=start + i + 1,
            heading=sc.get("heading", ""), location=sc.get("location", ""),
            time_of_day=sc.get("time_of_day", ""), summary=sc.get("summary", ""),
            action_text=sc.get("action_text", ""), dialogue=sc.get("dialogue", []) or [],
            style_overrides={"cast": sc.get("cast", []), "duration_sec": dur,
                             "pacing_profile": profile["id"]}, prev_scene_id=prev_id,
        )
        db.add(row)
        db.flush()
        prev_id = row.id
    db.commit()
    return script_public(db, s)


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def build_srt(db: Session, script: Script) -> str:
    scenes = db.query(Scene).filter(Scene.script_id == script.id).order_by(Scene.index).all()
    entries = []
    t = 0.0
    for sc in scenes:
        shot = db.query(Shot).filter(Shot.scene_id == sc.id).order_by(Shot.index).first()
        dur = shot.seconds if shot else 4.0
        if shot:
            render = (db.query(Render).filter(Render.shot_id == shot.id, Render.status == "succeeded",
                                              Render.video_asset_id.isnot(None))
                      .order_by(Render.created_at.desc()).first())
            if render:
                asset = db.get(Asset, render.video_asset_id)
                if asset and Path(asset.path).is_file():
                    info = await probe(asset.path)
                    if info.get("duration"):
                        dur = float(info["duration"])
        lines = [d for d in (sc.dialogue or []) if (d.get("line") or "").strip()]
        if lines:
            weights = [max(1, len(d["line"])) for d in lines]
            total = sum(weights)
            cur = t
            for d, w in zip(lines, weights):
                seg = dur * (w / total)
                name = d.get("character") or ""
                entries.append((cur + 0.1, min(t + dur, cur + seg - 0.05), f"{name}: {d['line']}".strip(": ")))
                cur += seg
        t += dur
    out = []
    for i, (a, b, text) in enumerate(entries, 1):
        out.append(f"{i}\n{_ts(a)} --> {_ts(b)}\n{text}\n")
    return "\n".join(out)


@router.get("/api/scripts/{script_id}/subtitles")
async def subtitles(script_id: str, db: Session = Depends(get_db)) -> dict:
    script = db.get(Script, script_id)
    if not script:
        raise HTTPException(404, "script not found")
    text = await build_srt(db, script)
    if not text.strip():
        raise HTTPException(422, "no dialogue to subtitle")
    asset = save_asset(db, text.encode("utf-8"), "text", "srt", mime="application/x-subrip",
                       meta={"script": script.id, "kind": "subtitles"})
    db.commit()
    return {"asset_id": asset.id, "url": asset_url(asset.id), "srt": text}
