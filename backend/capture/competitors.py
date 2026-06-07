"""LLM-based competitor auto-detection at the project level.

Replaces the old noisy per-run NER inference: gathers the project's domain,
prompts, and recent AI responses, then asks Gemini to extract clean competitor
brands. Inserted competitors are flagged inferred=True.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.database.session import session_scope
from backend.llm import gemini, service as llm_service
from backend.models import Competitor, Project, Run
from backend.storage import backends as storage

logger = logging.getLogger(__name__)


async def detect_competitors_for_project(project_id: int, max_runs: int = 30) -> list[dict]:
    """Detect and persist competitors. Returns the list of newly added competitors."""
    if not gemini.is_configured():
        logger.info("competitor detection skipped: GEMINI_API_KEY not set")
        return []

    with session_scope() as db:
        project = db.get(Project, project_id)
        if project is None:
            return []
        domain = project.domain
        prompts = [p.prompt_text for p in project.prompts]
        known = [c.competitor_name for c in project.competitors]
        runs = db.scalars(
            select(Run)
            .where(Run.project_id == project_id, Run.raw_json_path.is_not(None))
            .order_by(Run.created_at.desc())
            .limit(max_runs)
        ).all()
        raw_refs = [r.raw_json_path for r in runs]

    response_texts: list[str] = []
    for ref in raw_refs:
        try:
            raw = storage.load_json(ref)
            txt = raw.get("response_text") or ""
            if txt:
                response_texts.append(txt)
        except Exception:
            continue

    if not response_texts:
        return []

    detected = await llm_service.detect_competitors(domain, prompts, response_texts, known=known)
    if not detected:
        return []

    added: list[dict] = []
    with session_scope() as db:
        project = db.get(Project, project_id)
        if project is None:
            return []
        existing = {c.competitor_name.lower() for c in project.competitors}
        for comp in detected:
            name = comp["name"]
            if name.lower() in existing:
                continue
            db.add(Competitor(project_id=project_id, competitor_name=name, inferred=True))
            existing.add(name.lower())
            added.append(comp)

    logger.info("competitor detection: added %d for project %s", len(added), project_id)
    return added
