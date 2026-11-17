from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def _migrate() -> None:
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(characters)")}
        if "name_en" not in cols:
            conn.exec_driver_sql("ALTER TABLE characters ADD COLUMN name_en VARCHAR(120) DEFAULT ''")
        pcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(projects)")}
        if "pacing_profile" not in pcols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN pacing_profile VARCHAR(40) DEFAULT 'epic_historical'")
        if "target_duration_sec" not in pcols:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN target_duration_sec INTEGER DEFAULT 600")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
