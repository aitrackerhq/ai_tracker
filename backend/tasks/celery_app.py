"""Celery application — created only when a broker is configured.

When CELERY_BROKER_URL is unset, `celery_app` is None and the dispatcher in
jobs.py falls back to FastAPI BackgroundTasks (in-process). This keeps local
dev dependency-free while enabling durable, decoupled workers in production.

Run a worker with:
    celery -A backend.tasks.celery_app worker --loglevel=info
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit

from backend.config import settings

logger = logging.getLogger(__name__)


def _redact(url: str | None) -> str:
    """Strip any user:pass credentials from a broker URL before logging."""
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


celery_app = None

if settings.celery_enabled:
    try:
        from celery import Celery

        celery_app = Celery(
            "ai_tracker",
            broker=settings.celery_broker_url,
            backend=settings.celery_result_backend or settings.celery_broker_url,
            include=["backend.tasks.jobs"],
        )
        celery_app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            task_acks_late=True,            # re-deliver if a worker dies mid-task
            worker_prefetch_multiplier=1,   # one heavy scrape per worker at a time
            task_track_started=True,
            broker_connection_retry_on_startup=True,
            result_expires=3600,
        )
        logger.info("Celery enabled (broker=%s)", _redact(settings.celery_broker_url))
    except Exception:
        logger.exception("Celery init failed; falling back to in-process tasks")
        celery_app = None
