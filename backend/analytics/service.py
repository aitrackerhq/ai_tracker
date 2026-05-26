from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import Citation, Mention, Project, Run
from backend.ranking import compute_project_rankings


class AnalyticsService:
    """Read-only analytics derived from the database. The capture/processing layers feed it."""

    @staticmethod
    def overview(project_id: int) -> dict[str, Any]:
        rankings = compute_project_rankings(project_id)
        with session_scope() as db:
            project = db.get(Project, project_id)
            if project is None:
                return {}
            total_mentions = sum(b["mentions"] for b in rankings.get("brands", []))
            total_citations = sum(p["citations"] for p in rankings.get("providers", []))
            target = rankings.get("target") or {}
            return {
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "domain": project.domain,
                },
                "visibility_score": target.get("visibility_score", 0.0),
                "target_brand": target.get("brand"),
                "total_mentions": total_mentions,
                "total_citations": total_citations,
                "total_prompts": rankings.get("total_prompts", 0),
                "total_runs": rankings.get("total_runs", 0),
                "providers": rankings.get("providers", []),
                "top_brands": rankings.get("brands", [])[:10],
            }

    @staticmethod
    def runs(project_id: int) -> list[dict[str, Any]]:
        with session_scope() as db:
            runs = db.scalars(
                select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
            ).all()
            return [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "prompt": r.prompt,
                    "status": r.status,
                    "error": r.error,
                    "created_at": r.created_at.isoformat() + "Z",
                    "mention_count": len(r.mentions),
                    "citation_count": len(r.citations),
                    "has_target": any(m.is_target for m in r.mentions),
                    "screenshot_path": r.screenshot_path,
                    "raw_json_path": r.raw_json_path,
                }
                for r in runs
            ]

    @staticmethod
    def run_detail(run_id: int) -> dict[str, Any] | None:
        with session_scope() as db:
            r = db.get(Run, run_id)
            if r is None:
                return None
            return {
                "id": r.id,
                "provider": r.provider,
                "prompt": r.prompt,
                "status": r.status,
                "error": r.error,
                "created_at": r.created_at.isoformat() + "Z",
                "raw_json_path": r.raw_json_path,
                "processed_json_path": r.processed_json_path,
                "screenshot_path": r.screenshot_path,
                "html_path": r.html_path,
                "mentions": [
                    {
                        "entity_name": m.entity_name,
                        "normalized_entity": m.normalized_entity,
                        "mention_position": m.mention_position,
                        "is_target": m.is_target,
                    }
                    for m in sorted(r.mentions, key=lambda x: x.mention_position)
                ],
                "citations": [
                    {"domain": c.domain, "url": c.url, "title": c.title} for c in r.citations
                ],
            }

    @staticmethod
    def competitors(project_id: int) -> dict[str, Any]:
        rankings = compute_project_rankings(project_id)
        brands = rankings.get("brands", [])
        target = (rankings.get("target") or {}).get("brand")

        co_mention = Counter()
        with session_scope() as db:
            runs = db.scalars(select(Run).where(Run.project_id == project_id)).all()
            for r in runs:
                names = {m.normalized_entity for m in r.mentions}
                if target and target in names:
                    for n in names:
                        if n != target:
                            co_mention[n] += 1

        rows = []
        for b in brands:
            if b["is_target"]:
                continue
            rows.append({**b, "co_mention_with_target": co_mention.get(b["brand"], 0)})
        rows.sort(key=lambda x: x["co_mention_with_target"], reverse=True)
        return {"target": target, "competitors": rows}

    @staticmethod
    def provider_comparison(project_id: int) -> dict[str, Any]:
        rankings = compute_project_rankings(project_id)
        # brand-by-provider matrix
        with session_scope() as db:
            runs = db.scalars(select(Run).where(Run.project_id == project_id)).all()
            matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            providers: set[str] = set()
            for r in runs:
                providers.add(r.provider)
                for m in r.mentions:
                    matrix[m.normalized_entity][r.provider] += 1

        top = [b["brand"] for b in rankings.get("brands", [])[:8]]
        rows = []
        for brand in top:
            rows.append(
                {"brand": brand, **{p: matrix[brand].get(p, 0) for p in sorted(providers)}}
            )
        return {
            "providers": sorted(providers),
            "brands": rows,
            "summary": rankings.get("providers", []),
        }
