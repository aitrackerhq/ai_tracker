"""Background jobs + a dispatcher that prefers Celery and falls back to
FastAPI BackgroundTasks when no broker is configured.

Wrapping `run_capture` (which itself chains capture → storage → NER → ranking →
sentiment) means BOTH the scraping and the heavy NLP run off the web process
when Celery is enabled — keeping API responses fast.
"""
from __future__ import annotations

import logging

from backend.capture.orchestrator import run_capture
from backend.processing.pipeline import process_project
from backend.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


if celery_app is not None:

    @celery_app.task(name="ai_tracker.capture", bind=True, max_retries=3)
    def capture_task(self, run_ids: list[int], force_refresh: bool = False):
        try:
            return run_capture(run_ids, force_refresh)
        except Exception as exc:  # task-level retry with exponential backoff
            countdown = min(120, 5 * (2 ** self.request.retries))
            logger.warning("capture task retry in %ss: %s", countdown, exc)
            raise self.retry(exc=exc, countdown=countdown)

    @celery_app.task(name="ai_tracker.reprocess")
    def reprocess_task(project_id: int):
        return process_project(project_id)

else:
    capture_task = None
    reprocess_task = None


def submit_capture(run_ids: list[int], force_refresh: bool = False, background_tasks=None) -> str:
    """Dispatch a capture. Returns the execution mode used."""
    if capture_task is not None:
        capture_task.delay(run_ids, force_refresh)
        return "celery"
    if background_tasks is not None:
        background_tasks.add_task(run_capture, run_ids, force_refresh)
        return "background"
    run_capture(run_ids, force_refresh)  # synchronous last resort
    return "inline"


def submit_reprocess(project_id: int, background_tasks=None) -> tuple[str, int | None]:
    """Dispatch a reprocess. Returns (mode, count|None). Count is only known when
    run synchronously (Celery runs it async on a worker)."""
    if reprocess_task is not None:
        reprocess_task.delay(project_id)
        return "celery", None
    if background_tasks is not None:
        background_tasks.add_task(process_project, project_id)
        return "background", None
    count = process_project(project_id)
    return "inline", count
