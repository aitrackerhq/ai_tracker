from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import Citation, Mention, Project, Run
from backend.config import settings
from backend.processing.ner import EntityExtractor
from backend.processing.normalizer import EntityNormalizer
from backend.processing.sentiment import analyze_framing
from backend.storage import backends as storage
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
            raw = storage.load_json(run.raw_json_path)
        except Exception:
            logger.exception("failed to read raw json for run %s", run_pk)
            return None

        normalizer = _build_normalizer(project)
        extractor = EntityExtractor()

        response_text: str = raw.get("response_text") or ""
        target_key = _norm_key(brand_root_from_domain(project.domain) or project.name)
        target_brand = normalizer.canonical_for(target_key)

        # NER (spaCy) and sentiment (HF/torch) both read response_text independently
        # and both release the GIL during their native work, so running them on two
        # threads gives real overlap. Processing stays sequential ACROSS runs.
        raw_entities, framing = _extract_and_analyze(extractor, target_brand, response_text)

        # clear any prior processing
        for m in list(run.mentions):
            db.delete(m)
        for c in list(run.citations):
            db.delete(c)
        db.flush()

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
        processed_ref = storage.put_json(
            "processed", _run_uid_from_path(run.raw_json_path), processed_payload
        )
        run.processed_json_path = processed_ref

        # Local sentiment/framing of the target brand (computed above, in parallel
        # with NER). `framing` is None when sentiment is disabled or errored.
        if framing is not None:
            run.target_sentiment = framing.get("sentiment")
            run.target_framing = framing.get("framing")
            run.framing_rationale = framing.get("rationale")
        else:
            # keep reprocessing idempotent — clear any stale values
            run.target_sentiment = None
            run.target_framing = None
            run.framing_rationale = None

        run.status = "processed"

        # NOTE: competitor auto-detection is now done by the LLM at the project
        # level (backend.llm.service.detect_competitors), not by noisy per-run NER.
        # See backend.capture.competitors.detect_competitors_for_project.

        return processed_payload


def _extract_and_analyze(
    extractor: EntityExtractor, target_brand: str, response_text: str
):
    """Run NER and sentiment concurrently. Returns (raw_entities, framing|None)."""
    if not settings.enable_sentiment:
        return extractor.extract(response_text), None
    with ThreadPoolExecutor(max_workers=2) as ex:
        ner_future = ex.submit(extractor.extract, response_text)
        sentiment_future = ex.submit(_safe_framing, target_brand, response_text)
        return ner_future.result(), sentiment_future.result()


def _safe_framing(brand: str, text: str) -> dict | None:
    try:
        return analyze_framing(brand, text)
    except Exception:
        logger.exception("sentiment analysis failed")
        return None


def process_batch(run_ids: list[int]) -> list[int]:
    """Process captured runs **sequentially** (NER ∥ sentiment within each run),
    then run project-level competitor detection once.

    This is the processing phase that runs after the (parallel) capture phase —
    in the in-process path and as the Celery chord callback. Runs not in the
    'captured' state (errored / already-processed) are skipped. Returns the
    run_ids that were processed.
    """
    with session_scope() as db:
        rows = db.scalars(select(Run).where(Run.id.in_(run_ids))).all()
        # preserve the requested order — DB IN (...) return order is not guaranteed
        by_id = {r.id: r for r in rows}
        plan = [(rid, by_id[rid].project_id, by_id[rid].status) for rid in run_ids if rid in by_id]

    processed: list[int] = []
    project_ids: set[int] = set()
    for run_pk, project_id, status in plan:
        if status != "captured":
            continue
        try:
            process_run(run_pk)
            processed.append(run_pk)
            # only detect competitors for projects that actually processed a run
            project_ids.add(project_id)
        except Exception:
            logger.exception("processing failed for run %s", run_pk)

    _detect_competitors(project_ids)
    return processed


def _detect_competitors(project_ids: set[int]) -> None:
    """Project-level LLM competitor detection (best-effort). Imported lazily to
    avoid a circular import with the capture layer."""
    if not project_ids:
        return
    from backend.capture.competitors import detect_competitors_for_project

    async def _runner() -> None:
        for pid in project_ids:
            try:
                await detect_competitors_for_project(pid)
            except Exception:
                logger.exception("competitor detection failed for project %s", pid)

    asyncio.run(_runner())


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
