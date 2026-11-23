from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import config, settings_store
from .db import get_db, init_db
from .models import Asset
from .services import pacing
from .routers import characters, projects, renders, scenes, scripts, settings, voices

app = FastAPI(title="Shahnameh Film Studio", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(characters.router)
app.include_router(voices.router)
app.include_router(settings.router)
app.include_router(scripts.router)
app.include_router(scenes.router)
app.include_router(renders.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/pacing-profiles")
def pacing_profiles() -> dict:
    return {"data": pacing.list_profiles()}


@app.get("/api/health")
async def health(db: Session = Depends(get_db)) -> dict:
    cfg = settings_store.get_raw(db)
    out = {"studio": "ok", "image_provider": cfg["image"]["provider"], "video_provider": cfg["video"]["provider"],
           "tts_provider": cfg["tts"]["provider"], "llm_model": cfg["llm"]["model"]}
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(cfg["image"]["base_url"].rstrip("/") + "/v1/health")
            out["image_api"] = r.json()
    except Exception as exc:  # noqa: BLE001
        out["image_api"] = {"ok": False, "error": str(exc)[:200]}
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(cfg["video"]["base_url"].rstrip("/") + "/v1/health")
            out["video_api"] = r.json()
    except Exception as exc:  # noqa: BLE001
        out["video_api"] = {"ok": False, "error": str(exc)[:200]}
    return out


@app.get("/api/assets/{asset_id}/file")
def asset_file(asset_id: str, db: Session = Depends(get_db)) -> FileResponse:
    a = db.get(Asset, asset_id)
    if not a or not Path(a.path).is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(a.path, media_type=a.mime)


gallery = Path(config.DATA) / "gallery"
gallery.mkdir(parents=True, exist_ok=True)
app.mount("/gallery", StaticFiles(directory=str(gallery), html=True), name="gallery")

dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.is_dir():
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        page = dist / "index.html"
        if not page.is_file():
            raise HTTPException(404, "ui not built")
        return FileResponse(page, headers={"Cache-Control": "no-cache, must-revalidate"})

    app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")
