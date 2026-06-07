from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        # SQLite: allow cross-thread use (FastAPI threadpool + Celery worker).
        return create_engine(
            url, connect_args={"check_same_thread": False}, future=True
        )
    # Postgres / others. Supabase's pooled endpoint (port 6543) is pgbouncer in
    # transaction mode, which is incompatible with psycopg3 prepared statements —
    # disable them. pool_pre_ping + recycle recover connections dropped by the
    # pooler. These args are no-ops for non-psycopg drivers.
    connect_args = {}
    if "+psycopg" in url or url.startswith("postgresql://"):
        connect_args["prepare_threshold"] = None
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10,
        future=True,
    )


engine = _make_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
