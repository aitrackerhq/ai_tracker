from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import Citation, Competitor, Mention, Project, Run
from backend.processing.ner import EntityExtractor
from backend.processing.normalizer import EntityNormalizer
from backend.storage import processed_store, raw_store
from backend.utils.helpers import brand_root_from_domain, domain_from_url

logger = logging.getLogger(__name__)


def _build_normalizer(project: Project) -> EntityNormalizer:
    known: dict[str, list[str]] = {}
    # target brand
    root = brand_root_from_domain(project.domain) or project.name
    target_canonical = root.capitalize() if root else project.name
    known[target_canonical] = [project.name, project.domain, root]
    # explicit competitors
    for c in project.competitors:
        known[c.competitor_name] = [c.competitor_name]
    norm = EntityNormalizer(known)
    # seed domains
    norm.add_domain(_norm_key(target_canonical), project.domain)
    return norm


def _norm_key(s: str) -> str:
    from backend.processing.normalizer import normalize_name

    return normalize_name(s)


def process_run(run_pk: int) -> dict[str, Any] | None:
    """Load raw JSON for a run, do NER + normalization, persist mentions/citations.

    Idempotent: re-running clears existing mention/citation rows for the run.
    """
    with session_scope() as db:
        run = db.get(Run, run_pk)
        if run is None:
            return None
        if not run.raw_json_path:
            return None
        project = db.get(Project, run.project_id)
        if project is None:
            return None

        try:
            raw = raw_store.read(_run_uid_from_path(run.raw_json_path))
        except Exception:
            logger.exception("failed to read raw json for run %s", run_pk)
            return None

        normalizer = _build_normalizer(project)
        extractor = EntityExtractor()

        response_text: str = raw.get("response_text") or ""
        raw_entities = extractor.extract(response_text)

        # clear any prior processing
        for m in list(run.mentions):
            db.delete(m)
        for c in list(run.citations):
            db.delete(c)
        db.flush()

        target_key = _norm_key(brand_root_from_domain(project.domain) or project.name)
        position = 0
        for ent in raw_entities:
            ckey = normalizer.resolve(ent.text)
            if not ckey:
                continue
            position += 1
            db.add(
                Mention(
                    run_id=run.id,
                    entity_name=ent.text,
                    normalized_entity=normalizer.canonical_for(ckey),
                    mention_position=position,
                    is_target=(ckey == target_key),
                )
            )

        # citations from raw + links
        for cit in raw.get("citations") or []:
            url = cit.get("url") or ""
            if not url:
                continue
            d = cit.get("domain") or domain_from_url(url)
            if not d:
                continue
            db.add(
                Citation(
                    run_id=run.id,
                    domain=d,
                    url=url,
                    title=(cit.get("title") or None),
                )
            )

        # build processed output
        processed_payload = {
            "run_id": run.id,
            "provider": run.provider,
            "prompt": run.prompt,
            "raw_response_chars": len(response_text),
            "normalized_mentions": [
                {
                    "raw": ent.text,
                    "canonical": normalizer.canonical_for(_norm_key(ent.text))
                    if normalizer.resolve(ent.text) is not None
                    else ent.text,
                    "label": ent.label,
                    "position": idx + 1,
                }
                for idx, ent in enumerate(raw_entities)
            ],
            "citations": raw.get("citations") or [],
            "has_ai_overview": raw.get("has_ai_overview"),
        }
        processed_path = processed_store.write(_run_uid_from_path(run.raw_json_path), processed_payload)
        run.processed_json_path = str(processed_path)
        run.status = "processed"

        # opportunistically infer competitors (any non-target brand mentioned)
        existing = {c.competitor_name.lower() for c in project.competitors}
        for ckey, brand in normalizer.brands.items():
            if ckey == target_key:
                continue
            if brand.canonical.lower() in existing:
                continue
            if any(m.normalized_entity.lower() == brand.canonical.lower() for m in run.mentions):
                db.add(
                    Competitor(
                        project_id=project.id,
                        competitor_name=brand.canonical,
                        inferred=True,
                    )
                )
                existing.add(brand.canonical.lower())

        return processed_payload


def process_project(project_id: int) -> int:
    """Re-process every run in a project. Returns count."""
    count = 0
    with session_scope() as db:
        run_ids = [r.id for r in db.scalars(select(Run).where(Run.project_id == project_id)).all()]
    for rid in run_ids:
        process_run(rid)
        count += 1
    return count


def _run_uid_from_path(path: str) -> str:
    # raw paths are storage/raw/<uid>.json
    from pathlib import Path

    return Path(path).stem
