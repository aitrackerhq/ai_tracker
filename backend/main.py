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
    """Lightweight dialect-aware migration: add columns introduced after a DB was
    first created. Fresh DBs are fully created by create_all; this only upgrades
    existing ones in place. For complex Postgres migrations, prefer Alembic.
    """
    dialect = engine.dialect.name
    dt = "DATETIME" if dialect == "sqlite" else "TIMESTAMP"
    # logical (column, type) per table — types are portable across SQLite/Postgres
    # ("BOOLEAN DEFAULT FALSE" works on SQLite >= 3.23 and Postgres).
    pending: dict[str, list[tuple[str, str]]] = {
        "runs": [
            ("batch_id", "VARCHAR(64)"),
            ("geo_location", "VARCHAR(128)"),
            ("cached", "BOOLEAN DEFAULT FALSE"),
            ("target_sentiment", "VARCHAR(32)"),
            ("target_framing", "VARCHAR(32)"),
            ("framing_rationale", "TEXT"),
        ],
        "prompts": [("created_at", dt)],
        "competitors": [("created_at", dt)],
        "projects": [("geo_location", "VARCHAR(128)"), ("providers", "VARCHAR(255)")],
    }

    def _existing(conn, table: str) -> set[str] | None:
        try:
            if dialect == "sqlite":
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                return {r[1] for r in rows} or None
            rows = conn.exec_driver_sql(
                f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'"
            ).fetchall()
            return {r[0] for r in rows} or None
        except Exception:
            return None

    with engine.begin() as conn:
        for table, cols in pending.items():
            existing = _existing(conn, table)
            if existing is None:  # table not created yet → create_all handles it
                continue
            for col, coltype in cols:
                if dialect == "sqlite":
                    if col not in existing:
                        logger.info("migrating sqlite: add %s.%s", table, col)
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
                elif col not in existing:
                    logger.info("migrating %s: add %s.%s", dialect, table, col)
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {coltype}"
                    )


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
