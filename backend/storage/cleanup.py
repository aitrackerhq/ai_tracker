from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from backend.config import settings
from backend.database.session import session_scope
from backend.models import Run
from backend.storage.backends import delete_ref

logger = logging.getLogger(__name__)


_ARTIFACT_ATTRS = ("raw_json_path", "processed_json_path", "screenshot_path", "html_path")


def purge_run_files(run) -> int:
    """Delete all artifacts (local disk or R2) referenced by a Run row."""
    return sum(1 for attr in _ARTIFACT_ATTRS if delete_ref(getattr(run, attr, None)))


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
            cleared = True
            for attr in _ARTIFACT_ATTRS:
                ref = getattr(run, attr, None)
                if not ref:
                    continue
                if delete_ref(ref):
                    deleted_files += 1
                    setattr(run, attr, None)  # only null the ref once the file is gone
                else:
                    cleared = False
            # only mark purged if every artifact was removed, so failures retry later
            if cleared:
                run.status = "purged"
                purged_runs += 1

    logger.info("artifact purge: %d runs, %d files removed (ttl=%dd)", purged_runs, deleted_files, ttl_days)
    return {"runs_purged": purged_runs, "files_deleted": deleted_files, "ttl_days": ttl_days}
