"""Background jobs + a dispatcher that prefers Celery and falls back to
FastAPI BackgroundTasks when no broker is configured.

Capture is **fanned out one task per provider** so providers run in parallel
across workers; a chord callback then runs the heavy NLP (NER + sentiment)
**sequentially** in one place. The in-process fallback (`run_capture`) does the
same capture→process split inside a single process.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.capture.orchestrator import capture_provider, run_capture
from backend.database.session import session_scope
from backend.models import Run
from backend.processing.pipeline import process_batch, process_project
from backend.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _group_by_provider(run_ids: list[int]) -> dict[str, list[int]]:
    """Map provider → its run_ids, so each provider becomes one parallel task."""
    groups: dict[str, list[int]] = {}
    with session_scope() as db:
        rows = db.scalars(select(Run).where(Run.id.in_(run_ids))).all()
        for r in rows:
            groups.setdefault(r.provider, []).append(r.id)
    return groups


def _mark_runs_error(run_ids: list[int], message: str) -> None:
    """Mark the given runs as errored (used when a provider task gives up)."""
    with session_scope() as db:
        for run in db.scalars(select(Run).where(Run.id.in_(run_ids))).all():
            run.status = "error"
            run.error = message


if celery_app is not None:
    from celery import chord, group

    @celery_app.task(name="ai_tracker.capture_provider", bind=True, max_retries=3)
    def capture_provider_task(self, provider_name: str, run_ids: list[int], force_refresh: bool = False):
        """Capture one provider's runs (parallel across workers). No processing."""
        try:
            return capture_provider(provider_name, run_ids, force_refresh)
        except Exception as exc:
            if self.request.retries < self.max_retries:  # transient: back off + retry
                countdown = min(120, 5 * (2 ** self.request.retries))
                logger.warning("capture_provider(%s) retry in %ss: %s", provider_name, countdown, exc)
                raise self.retry(exc=exc, countdown=countdown)
            # Give up — mark these runs errored and return so the chord callback
            # still runs and processes the providers that DID succeed.
            logger.exception("capture_provider(%s) gave up after retries", provider_name)
            _mark_runs_error(run_ids, repr(exc))
            return []

    @celery_app.task(name="ai_tracker.process_batch")
    def process_batch_task(results: list[list[int]]):
        """Chord callback: flatten the per-provider run_id lists and process them
        sequentially (NER ∥ sentiment per run + competitor detection)."""
        run_ids = [rid for sub in results if sub for rid in sub]
        return process_batch(run_ids)

    @celery_app.task(name="ai_tracker.reprocess")
    def reprocess_task(project_id: int):
        """Celery task: re-run NLP processing for every run in a project."""
        return process_project(project_id)

else:
    capture_provider_task = None
    process_batch_task = None
    reprocess_task = None


def submit_capture(run_ids: list[int], force_refresh: bool = False, background_tasks=None) -> str:
    """Dispatch a capture. Returns the execution mode used."""
    if capture_provider_task is not None:
        groups = _group_by_provider(run_ids)
        if groups:
            header = group(
                capture_provider_task.s(provider, ids, force_refresh)
                for provider, ids in groups.items()
            )
            chord(header)(process_batch_task.s())
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
