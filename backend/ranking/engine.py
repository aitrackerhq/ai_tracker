from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import Citation, Mention, Project, Run
from backend.utils.helpers import brand_root_from_domain


@dataclass
class BrandStats:
    name: str
    mentions: int = 0
    runs_seen: set[int] = field(default_factory=set)
    prompts_seen: set[str] = field(default_factory=set)
    providers_seen: set[str] = field(default_factory=set)
    positions: list[int] = field(default_factory=list)
    first_mentions: int = 0          # times this brand was the #1 mention in a run
    citations: int = 0

    def visibility_score(self, total_prompts: int) -> float:
        if total_prompts == 0:
            return 0.0
        base = (len(self.prompts_seen) / total_prompts) * 100
        first_bonus = (self.first_mentions / max(1, len(self.runs_seen))) * 10
        citation_bonus = min(self.citations, 5) * 2
        provider_bonus = (len(self.providers_seen) - 1) * 5 if len(self.providers_seen) > 1 else 0
        return round(min(100.0, base + first_bonus + citation_bonus + provider_bonus), 2)

    def avg_position(self) -> float | None:
        if not self.positions:
            return None
        return round(sum(self.positions) / len(self.positions), 2)


class RankingEngine:
    def __init__(self, project_id: int):
        self.project_id = project_id

    def compute(self) -> dict[str, Any]:
        with session_scope() as db:
            project = db.get(Project, self.project_id)
            if project is None:
                return {}
            runs: list[Run] = list(
                db.scalars(select(Run).where(Run.project_id == self.project_id)).all()
            )
            target_root = brand_root_from_domain(project.domain) or project.name
            prompts_total = {r.prompt for r in runs}

            stats: dict[str, BrandStats] = defaultdict(lambda: BrandStats(name=""))
            provider_stats: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"runs": 0, "with_target": 0, "citations": 0, "errors": 0}
            )
            target_canon = None

            for run in runs:
                provider_stats[run.provider]["runs"] += 1
                if run.status == "error":
                    provider_stats[run.provider]["errors"] += 1
                provider_stats[run.provider]["citations"] += len(run.citations)

                # mentions
                seen_in_run: set[str] = set()
                for m in sorted(run.mentions, key=lambda x: x.mention_position):
                    name = m.normalized_entity
                    s = stats[name]
                    s.name = name
                    s.mentions += 1
                    s.runs_seen.add(run.id)
                    s.prompts_seen.add(run.prompt)
                    s.providers_seen.add(run.provider)
                    s.positions.append(m.mention_position)
                    if m.mention_position == 1:
                        s.first_mentions += 1
                    seen_in_run.add(name)
                    if m.is_target:
                        target_canon = name

                if target_canon and target_canon in seen_in_run:
                    provider_stats[run.provider]["with_target"] += 1

                for c in run.citations:
                    # attribute to a brand only if domain root matches a known brand
                    root = brand_root_from_domain(c.domain)
                    for name in list(stats.keys()):
                        if brand_root_from_domain(name) == root or name.lower() == root:
                            stats[name].citations += 1
                            break

            prompt_count = len(prompts_total)        # real value for display
            denom = prompt_count or 1                 # div-by-zero guard for scoring
            brand_rows = []
            for name, s in stats.items():
                brand_rows.append(
                    {
                        "brand": name,
                        "is_target": (name == target_canon),
                        "mentions": s.mentions,
                        "prompts_appeared_in": len(s.prompts_seen),
                        "providers": sorted(s.providers_seen),
                        "avg_position": s.avg_position(),
                        "first_mentions": s.first_mentions,
                        "citations": s.citations,
                        "visibility_score": s.visibility_score(denom),
                    }
                )
            brand_rows.sort(key=lambda x: x["visibility_score"], reverse=True)

            target_row = next((b for b in brand_rows if b["is_target"]), None)
            return {
                "project_id": self.project_id,
                "total_prompts": prompt_count,
                "total_runs": len(runs),
                "target": target_row,
                "brands": brand_rows,
                "providers": [
                    {
                        "provider": p,
                        "runs": d["runs"],
                        "errors": d["errors"],
                        "with_target": d["with_target"],
                        "citations": d["citations"],
                        "target_share": round((d["with_target"] / d["runs"]) * 100, 2) if d["runs"] else 0.0,
                    }
                    for p, d in provider_stats.items()
                ],
            }


def compute_project_rankings(project_id: int) -> dict[str, Any]:
    return RankingEngine(project_id).compute()
