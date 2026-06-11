"""Shared test fixtures — an isolated in-memory SQLite bound to the scoring engine."""
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base


@pytest.fixture
def db_scope(monkeypatch):
    """A session_scope bound to a fresh in-memory DB, patched into the scoring engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection → in-memory DB persists across sessions
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _scope():
        db = TestSession()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr("backend.scoring.engine.session_scope", _scope)
    return _scope
