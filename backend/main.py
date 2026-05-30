from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import settings
from backend.database.session import engine
from backend.models import Base
from backend.storage import purge_expired

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _ensure_columns() -> None:
    """Lightweight SQLite-only migration: add columns introduced after a DB was
    first created. SQLite allows ADD COLUMN; nullable so existing rows stay valid.
    """
    pending = {
        "runs": [
            ("batch_id", "ALTER TABLE runs ADD COLUMN batch_id VARCHAR(64)"),
            ("geo_location", "ALTER TABLE runs ADD COLUMN geo_location VARCHAR(128)"),
            ("cached", "ALTER TABLE runs ADD COLUMN cached BOOLEAN DEFAULT 0"),
            ("target_sentiment", "ALTER TABLE runs ADD COLUMN target_sentiment VARCHAR(32)"),
            ("target_framing", "ALTER TABLE runs ADD COLUMN target_framing VARCHAR(32)"),
            ("framing_rationale", "ALTER TABLE runs ADD COLUMN framing_rationale TEXT"),
        ],
        "prompts": [("created_at", "ALTER TABLE prompts ADD COLUMN created_at DATETIME")],
        "competitors": [("created_at", "ALTER TABLE competitors ADD COLUMN created_at DATETIME")],
        "projects": [
            ("geo_location", "ALTER TABLE projects ADD COLUMN geo_location VARCHAR(128)"),
            ("providers", "ALTER TABLE projects ADD COLUMN providers VARCHAR(255)"),
        ],
    }
    with engine.begin() as conn:
        for table, cols in pending.items():
            try:
                existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            except Exception:
                continue
            if not existing:  # table doesn't exist yet (fresh DB handled by create_all)
                continue
            for col, ddl in cols:
                if col not in existing:
                    logger.info("migrating: %s", ddl)
                    conn.exec_driver_sql(ddl)


async def _cleanup_loop() -> None:
    """Periodic artifact purge. Runs once at startup, then every N hours.
    Lightweight in-process scheduler — no Celery/cron dependency for the MVP.
    """
    interval = max(1, settings.cleanup_interval_hours) * 3600
    while True:
        try:
            await asyncio.to_thread(purge_expired)
        except Exception:
            logger.exception("artifact cleanup failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    app = FastAPI(title="AI Search Visibility Tracker", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host=settings.api_host, port=settings.api_port, reload=False)
