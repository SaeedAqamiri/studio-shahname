from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import Asset


def save_asset(db: Session, raw: bytes, kind: str, ext: str = "png", mime: str | None = None,
               meta: dict | None = None) -> Asset:
    digest = hashlib.sha256(raw).hexdigest()
    a = Asset(kind=kind, path="", mime=mime or ("image/png" if kind == "image" else "application/octet-stream"),
              sha256=digest, meta=meta or {})
    db.add(a)
    db.flush()
    path = config.ASSETS / f"{a.id}.{ext}"
    path.write_bytes(raw)
    a.path = str(path)
    db.flush()
    return a


def asset_url(asset_id: str | None) -> str | None:
    return f"/api/assets/{asset_id}/file" if asset_id else None
