#!/usr/bin/env python3
"""Unattended Shahnameh film pipeline.

Phase A: compile a visual prompt per scene and render one look frame.
Phase B: split every scene into 2-3 LTX shots and submit them to the video queue.
Phase C: poll renders, save every clip, and build the final cut per film.
Everything is mirrored into data/gallery/ and served at /gallery/.
"""
from __future__ import annotations

import html
import json
import os
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from app.db import SessionLocal  # noqa: E402
from app.models import Asset, CastMember, Project, Render, Scene, Script, Shot  # noqa: E402
from app.services import pacing  # noqa: E402

BASE = "http://127.0.0.1:8099"
PROJECT = "a61ca3b98fce45fbabeba7f94d793103"
FILM_NUMBERS = [1, 2, 3, 4, 5, 11]
DATA = Path(__file__).resolve().parent / "data"
GALLERY = DATA / "gallery"
LOG_PATH = DATA / "film_pipeline.log"
STATUS_PATH = GALLERY / "status.json"
POLL_SECONDS = 20
MAX_RETRIES = 3


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def api(path: str, method: str = "GET", body=None, timeout: int = 180):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def download(url: str, dest: Path, timeout: int = 300) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(BASE + url if url.startswith("/") else url,
                                 headers={"User-Agent": "shahnameh-pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def safe_name(s: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "").strip("_")
    return s or fallback


def init_gallery() -> dict:
    for sub in ("films", "look_frames", "shots", "characters"):
        (GALLERY / sub).mkdir(parents=True, exist_ok=True)
    chars = api(f"/api/projects/{PROJECT}/characters")["data"]
    meta = []
    for c in chars:
        if c.get("canonical_url"):
            ext = ".png"
            name = safe_name(c.get("name_en"), c["id"])
            dest = GALLERY / "characters" / f"{name}{ext}"
            try:
                download(c["canonical_url"], dest)
            except Exception as e:
                log(f"CHAR IMG FAIL {c.get('name')}: {e}")
        meta.append({"name": c.get("name"), "name_en": c.get("name_en"),
                     "role": c.get("role"), "description": c.get("description"),
                     "image": f"characters/{safe_name(c.get('name_en'), c['id'])}.png"})
    (GALLERY / "characters.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {"chars": meta}


def load_films() -> list[dict]:
    rows = api(f"/api/projects/{PROJECT}/scripts")["data"]
    out = []
    for s in rows:
        n = (s.get("meta") or {}).get("film_no")
        if n in FILM_NUMBERS:
            full = api(f"/api/scripts/{s['id']}")
            out.append(full)
    return sorted(out, key=lambda x: (x.get("meta") or {}).get("film_no", 99))


def compile_prompt(scene: dict) -> dict:
    ov = scene.get("style_overrides") or {}
    if ov.get("visual_prompt"):
        return ov
    for attempt in range(3):
        try:
            r = api(f"/api/scenes/{scene['id']}/compile", method="POST", body={}, timeout=180)
            return {"visual_prompt": r.get("visual_prompt", ""), "negative": r.get("negative", "")}
        except Exception as e:
            log(f"COMPILE FAIL scene {scene.get('index')} attempt {attempt+1}: {e}")
            time.sleep(2 + attempt * 3)
    return {"visual_prompt": "", "negative": ""}


def build_prompt(film: dict, scene: dict, profile_id: str) -> str:
    ov = scene.get("style_overrides") or {}
    style_note = pacing.get_profile(profile_id)["style_note"]
    vp = ov.get("visual_prompt") or ""
    if not vp:
        cast = ", ".join((ov.get("cast") or []))
        vp = (f"{scene.get('heading','')}. {scene.get('location','')}. {scene.get('time_of_day','')}. "
              f"{scene.get('summary','')}. {scene.get('action_text','')}. Characters: {cast}.")
    return vp + ", " + style_note


def look_frame(scene: dict, prompt: str) -> str | None:
    try:
        r = api(f"/api/scenes/{scene['id']}/look-frame", method="POST", body={
            "prompt": prompt, "width": 960, "height": 540, "use_cast_references": True}, timeout=300)
        asset_id = r.get("look_frame_id")
        if r.get("url"):
            dest = GALLERY / "look_frames" / f"film_{scene['_film']}_scene_{scene['index']:02d}.png"
            download(r["url"], dest)
        return asset_id
    except Exception as e:
        log(f"LOOK FAIL film {scene['_film']} scene {scene['index']}: {e}")
        return None


def ensure_shots(db, film: dict, scene: Scene, look_id: str | None, profile_id: str) -> list[Shot]:
    existing = db.query(Shot).filter(Shot.scene_id == scene.id).order_by(Shot.index).all()
    if existing:
        return existing
    profile = pacing.get_profile(profile_id)
    ov = scene.style_overrides or {}
    base_prompt = ov.get("visual_prompt") or scene.summary or scene.heading
    negative = (ov.get("negative") or "") + ", " + profile["negative_note"]
    dur = int(round(float(ov.get("duration_sec") or 25)))
    parts = pacing.split_scene(dur, profile_id)
    cast_snapshot = [{"character_id": c.character_id, "variant_id": c.variant_id}
                     for c in db.query(CastMember).filter(CastMember.scene_id == scene.id).all()]
    shots = []
    for i, part in enumerate(parts):
        first = look_id if i == 0 else None
        shot = Shot(
            scene_id=scene.id, index=i + 1,
            prompt=pacing.shot_prompt(part["kind"]) + ", " + base_prompt + ", " + profile["style_note"],
            negative=negative, mode="i2v" if first else "t2v",
            width=1280, height=720, fps=24.0, seconds=float(part["seconds"]),
            seed=random.randint(1, 2**31 - 1), generate_audio=True,
            first_frame_id=first, status="ready", cast_snapshot=cast_snapshot,
        )
        db.add(shot)
        shots.append(shot)
    db.commit()
    for s in shots:
        db.refresh(s)
    log(f"SHOTS film {film['meta'].get('film_no')} scene {scene.index}: "
        f"{[(p['kind'], p['seconds']) for p in parts]} profile={profile_id}")
    return shots


def submit_pending(db, shot: Shot) -> bool:
    sid = shot.id
    renders = db.query(Render).filter(Render.shot_id == sid).order_by(Render.created_at.desc()).all()
    statuses = [r.status for r in renders]
    db.rollback()
    if any(s in ("queued", "running", "succeeded") for s in statuses):
        return False
    if sum(1 for s in statuses if s == "failed") >= MAX_RETRIES:
        return False
    try:
        api(f"/api/shots/{sid}/render", method="POST", body={}, timeout=60)
        return True
    except Exception as e:
        log(f"SUBMIT FAIL shot {sid}: {e}")
        return False


def poll_once(db, shot_meta: dict) -> tuple[int, int]:
    pending = db.query(Render).filter(Render.status.in_(["queued", "running"])) \
        .order_by(Render.created_at).limit(12).all()
    items = [(r.id, r.shot_id) for r in pending]
    db.rollback()
    ok = 0
    fail = 0
    for rid, sid in items:
        try:
            j = api(f"/api/renders/{rid}", timeout=180)
        except Exception as e:
            log(f"POLL FAIL render {rid}: {e}")
            continue
        st = j.get("status")
        if st == "succeeded" and j.get("video_url"):
            info = shot_meta.get(sid)
            if info:
                n, si, sh = info
                dest = GALLERY / "shots" / f"film_{n}_scene_{si:02d}_shot_{sh}.mp4"
                if not dest.exists():
                    try:
                        download(j["video_url"], dest, timeout=600)
                    except Exception as e:
                        log(f"SHOT COPY FAIL {dest.name}: {e}")
            ok += 1
        elif st == "failed":
            fail += 1
            info = shot_meta.get(sid)
            log(f"RENDER FAILED render={rid} shot={sid} info={info} err={(j.get('error') or '')[:160]}")
    return ok, fail


def render_counts(db, script_id: str) -> dict:
    scenes = db.query(Scene).filter(Scene.script_id == script_id).order_by(Scene.index).all()
    total = done = failed = 0
    for sc in scenes:
        shots = db.query(Shot).filter(Shot.scene_id == sc.id).all()
        for sh in shots:
            total += 1
            rs = db.query(Render).filter(Render.shot_id == sh.id).all()
            if any(r.status == "succeeded" and r.video_asset_id for r in rs):
                done += 1
            elif rs and all(r.status in ("failed", "cancelled") for r in rs):
                failed += 1
    return {"total": total, "done": done, "failed": failed, "scenes": len(scenes)}


def write_status(films: list[dict], phase: str, extra: dict | None = None) -> None:
    out = {"updated": time.time(), "phase": phase, "films": []}
    try:
        with SessionLocal() as db:
            for f in films:
                c = render_counts(db, f["id"])
                out["films"].append({"no": f["meta"].get("film_no"), "title": f["title"],
                                     "scenes": c["scenes"], "shots": c["total"],
                                     "done": c["done"], "failed": c["failed"]})
    except Exception as e:
        out["error"] = str(e)
    if extra:
        out.update(extra)
    STATUS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))


def write_pages(films: list[dict]) -> None:
    chars = json.loads((GALLERY / "characters.json").read_text()) if (GALLERY / "characters.json").exists() else []
    cards = []
    for f in films:
        n = f["meta"].get("film_no")
        final = GALLERY / "films" / f"film_{n}.mp4"
        status = "آماده" if final.exists() else "در حال ساخت"
        cards.append(f'<div class="card"><h3>{html.escape(f["title"])}</h3>'
                     f'<p>{status} · {len(f.get("scenes") or [])} صحنه</p>'
                     f'<a href="film_{n}.html">دیدن فیلم و تصاویر</a></div>')
        rows = []
        for sc in f.get("scenes") or []:
            img = f"look_frames/film_{n}_scene_{sc['index']:02d}.png"
            rows.append(f'<figure><img loading="lazy" src="{img}" alt=""><figcaption>'
                        f'{sc["index"]}. {html.escape(sc.get("heading") or "")}</figcaption></figure>')
        vid = f'<video controls preload="metadata" src="films/film_{n}.mp4"></video>' if final.exists() else '<p class="muted">ویدیو هنوز آماده نیست.</p>'
        shot_items = []
        shot_dir = GALLERY / "shots"
        for p in sorted(shot_dir.glob(f"film_{n}_scene_*_shot_*.mp4")):
            shot_items.append(f'<div class="shot"><video controls preload="metadata" src="shots/{p.name}"></video>'
                              f'<small>{html.escape(p.name)}</small></div>')
        (GALLERY / f"film_{n}.html").write_text(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<title>{html.escape(f["title"])}</title><style>
body{{background:#141414;color:#eee;font-family:system-ui,sans-serif;margin:0 auto;max-width:1300px;padding:24px}}
a{{color:#e8b45a}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}}
figure{{margin:0;background:#1e1e1e;padding:8px;border-radius:10px}} img{{width:100%;border-radius:6px}}
figcaption{{font-size:12px;color:#bbb;margin-top:6px}} video{{width:100%;max-height:520px;border-radius:10px;background:#000}}
.shots{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
.shot small{{color:#888}} .muted{{color:#888}}</style>
<p><a href="index.html">← گالری</a></p><h1>{html.escape(f["title"])}</h1>{vid}
<h2>فریم‌های نگاه</h2><div class="grid">{"".join(rows)}</div>
<details><summary><h2 style="display:inline">شات‌ها ({len(shot_items)})</h2></summary><div class="shots">{"".join(shot_items)}</div></details>
</html>""")
    char_cards = "".join(
        f'<div class="card"><img src="{c["image"]}" alt=""><h4>{html.escape(c.get("name") or "")}</h4>'
        f'<p>{html.escape(c.get("role") or "")}</p></div>' for c in chars if (GALLERY / c["image"]).exists())
    (GALLERY / "index.html").write_text(f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<title>گالری شاهنامه</title><style>
body{{background:#141414;color:#eee;font-family:system-ui,sans-serif;margin:0 auto;max-width:1300px;padding:24px}}
a{{color:#e8b45a}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}}
.card{{background:#1e1e1e;border-radius:12px;padding:12px}} .card img{{width:100%;border-radius:8px;aspect-ratio:3/4;object-fit:cover}}
h4{{margin:8px 0 2px}} p{{color:#bbb;font-size:13px}}</style>
<h1>گالری شاهنامه</h1><p><a href="progress.html">📊 پیشرفت رندر شات‌ها</a> · فیلم‌ها، فریم‌های نگاه و شخصیت‌ها — به‌روزرسانی: {time.strftime('%Y-%m-%d %H:%M')}</p>
<h2>فیلم‌ها</h2><div class="grid">{"".join(cards)}</div>
<h2>شخصیت‌ها</h2><div class="grid">{char_cards}</div></html>""")


def finalize_film(db, film: dict) -> bool:
    n = film["meta"].get("film_no")
    final = GALLERY / "films" / f"film_{n}.mp4"
    if final.exists():
        return True
    counts = render_counts(db, film["id"])
    if counts["total"] == 0:
        return False
    if counts["done"] < counts["total"] and counts["failed"] == 0:
        return False
    if counts["done"] == 0:
        log(f"FINAL SKIP film {n}: no succeeded shots")
        return False
    db.rollback()
    try:
        log(f"FINAL START film {n} done={counts['done']}/{counts['total']} failed={counts['failed']}")
        r = api(f"/api/projects/{PROJECT}/edit", method="POST", body={"script_id": film["id"]}, timeout=1800)
        if r.get("url"):
            download(r["url"], final, timeout=1800)
            log(f"FINAL OK film {n} {r.get('duration')}s {r.get('clips')} clips -> {final}")
            return True
    except Exception as e:
        log(f"FINAL FAIL film {n}: {e}")
    return False


def main() -> None:
    log(f"=== PIPELINE START films={FILM_NUMBERS} ===")
    init_gallery()
    films = load_films()
    project = api(f"/api/projects/{PROJECT}")
    profile_id = project.get("pacing_profile") or pacing.DEFAULT_PROFILE
    target_sec = project.get("target_duration_sec") or 600
    log(f"loaded {len(films)} films: " + ", ".join(f"{f['meta'].get('film_no')}:{f['title']}" for f in films))
    log(f"pacing profile={profile_id} target={target_sec}s shots_plan={pacing.get_profile(profile_id)['shots_per_scene']}")
    write_pages(films)

    # Phase A: compile + look frames
    write_status(films, "look_frames")
    for f in films:
        n = f["meta"].get("film_no")
        for sc in f.get("scenes") or []:
            sc["_film"] = n
            ov = compile_prompt(sc)
            prompt = build_prompt(f, {**sc, "style_overrides": {**(sc.get("style_overrides") or {}), **ov}}, profile_id)
            if not (GALLERY / "look_frames" / f"film_{n}_scene_{sc['index']:02d}.png").exists():
                look_frame(sc, prompt)
        log(f"LOOK PHASE film {n} done")

    # Phase B: create shots and submit
    write_status(films, "submitting")
    shot_meta = {}
    with SessionLocal() as db:
        for f in films:
            n = f["meta"].get("film_no")
            for sc in f.get("scenes") or []:
                scene = db.get(Scene, sc["id"])
                if not scene:
                    continue
                lf = scene.look_frame_id
                shots = ensure_shots(db, f, scene, lf, profile_id)
                for sh in shots:
                    sid, shi = sh.id, sh.index
                    shot_meta[sid] = (n, scene.index, shi)
                    submit_pending(db, sh)
        db.commit()
    log(f"SUBMITTED shots={len(shot_meta)}")

    # Phase C: poll, copy, finalize
    write_status(films, "rendering")
    retries = {}
    last_status = 0
    while True:
        pending = 0
        total = done = failed = 0
        with SessionLocal() as db:
            poll_once(db, shot_meta)
            for f in films:
                counts = render_counts(db, f["id"])
                if counts["done"] + counts["failed"] >= counts["total"] and counts["total"] > 0:
                    finalize_film(db, f)
            failed_shots = []
            for sid in shot_meta:
                rs = db.query(Render).filter(Render.shot_id == sid).all()
                statuses = [r.status for r in rs]
                if statuses and all(s in ("failed", "cancelled") for s in statuses):
                    if retries.get(sid, 0) < MAX_RETRIES:
                        retries[sid] = retries.get(sid, 0) + 1
                        failed_shots.append(sid)
            db.rollback()
            for sid in failed_shots:
                try:
                    api(f"/api/shots/{sid}/render", method="POST", body={}, timeout=60)
                except Exception as e:
                    log(f"RETRY SUBMIT FAIL {sid}: {e}")
            pending = db.query(Render).filter(Render.status.in_(["queued", "running"])).count()
            for f in films:
                c = render_counts(db, f["id"])
                total += c["total"]; done += c["done"]; failed += c["failed"]
            db.rollback()
        done_films = sum(1 for f in films if (GALLERY / "films" / f"film_{f['meta'].get('film_no')}.mp4").exists())
        write_pages(films)
        if time.time() - last_status > 30:
            write_status(films, "rendering")
            last_status = time.time()
        log(f"PROGRESS films_done={done_films}/{len(films)} shots_done={done}/{total} failed={failed} pending={pending}")
        if done_films == len(films):
            write_status(films, "done")
            break
        if pending == 0 and failed >= total and total > 0:
            log("ALL SHOTS FAILED — stopping")
            write_status(films, "failed")
            break
        time.sleep(POLL_SECONDS)
    log("=== PIPELINE DONE ===")


if __name__ == "__main__":
    main()
