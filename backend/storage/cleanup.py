from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from backend.config import settings
from backend.database.session import session_scope
from backend.models import Run

logger = logging.getLogger(__name__)


_ARTIFACT_ATTRS = ("raw_json_path", "processed_json_path", "screenshot_path", "html_path")


def _safe_unlink(path_str: str | None) -> bool:
    if not path_str:
        return False
    try:
        p = Path(path_str)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        logger.warning("failed to delete artifact: %s", path_str)
    return False


def purge_run_files(run) -> int:
    """Delete all on-disk artifacts referenced by a Run row. Returns files removed."""
    return sum(1 for attr in _ARTIFACT_ATTRS if _safe_unlink(getattr(run, attr, None)))


def purge_expired(ttl_days: int | None = None) -> dict[str, int]:
    """Delete raw JSON + screenshot + HTML for runs older than the TTL.

    Aggregated DB rows (runs, mentions, citations) are kept — only the heavy
    on-disk artifacts are removed. The run's path columns are nulled and it's
    marked status='purged' so the UI can show it's no longer reprocessable.
    """
    ttl_days = ttl_days if ttl_days is not None else settings.artifact_ttl_days
    cutoff = datetime.utcnow() - timedelta(days=ttl_days)
    deleted_files = 0
    purged_runs = 0

    with session_scope() as db:
        stale = db.scalars(
            select(Run).where(Run.created_at < cutoff, Run.status != "purged")
        ).all()
        for run in stale:
            removed = False
            for attr in ("raw_json_path", "processed_json_path", "screenshot_path", "html_path"):
                path = getattr(run, attr, None)
                if _safe_unlink(path):
                    deleted_files += 1
                    removed = True
                setattr(run, attr, None)
            run.status = "purged"
            if removed or True:
                purged_runs += 1

    logger.info("artifact purge: %d runs, %d files removed (ttl=%dd)", purged_runs, deleted_files, ttl_days)
    return {"runs_purged": purged_runs, "files_deleted": deleted_files, "ttl_days": ttl_days}
