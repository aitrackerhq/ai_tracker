"""GEO scoring engine — computes the six-component composite score per brand.

Maps the scoring spec onto this project's real schema:
  - "workspace"  → Project
  - "brand"      → a normalized entity (the project's target brand, or a competitor)
  - "capture"    → a processed Run

The engine produces a deterministic snapshot: the six components (P1-P6), the
composite GEO_raw, the confidence scalar, and GEO_final, plus reliability metadata.
EMA smoothing and period-over-period significance are layered at persistence time
(they need stored history), not here — keeping this snapshot reproducible.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select

from backend.database.session import session_scope
from backend.models import Competitor, Project, Run
from backend.scoring import components as C
from backend.scoring.config import (
    ScoringConfig,
    mention_type_weight,
    provider_weight,
)
from backend.scoring.config import (
    SENTIMENT_LABEL_COMPOUND as _SENT,
)
from backend.utils.helpers import brand_root_from_domain

_SCORED_STATUS = "processed"  # only fully-processed runs carry mention data


@dataclass
class BrandScore:
    """Full deterministic score breakdown for one brand within a project."""

    brand: str
    is_target: bool
    # six components in [0,1]; sov is None when unavailable
    presence: float = 0.0
    position: float = 0.0
    citation: float = 0.0
    sentiment: float = 0.5
    sov: float | None = None
    provider: float = 0.0
    # composite chain
    geo_raw: float = 0.0
    confidence_scalar: float = 0.0
    geo_adjusted: float = 0.0
    geo_final: float = 0.0  # 0-100, one decimal
    # audit / reliability
    wilson_ci_lower: float = 0.0
    wilson_ci_upper: float = 1.0
    confidence_level: str = "insufficient"
    estimation_method: str = "wilson"
    sov_available: bool = False
    n_captures: int = 0
    n_appeared: int = 0
    # raw display stats (kept for dashboard back-compat)
    mentions: int = 0
    prompts_appeared_in: int = 0
    providers: list[str] = field(default_factory=list)
    avg_position: float | None = None
    first_mentions: int = 0
    citations: int = 0

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        # dashboard back-compat: expose the headline score under the legacy key
        d["visibility_score"] = self.geo_final
        return d


@dataclass
class _Raw:
    """Mutable per-brand accumulator while scanning runs."""

    name: str
    appeared_run_ids: set[int] = field(default_factory=set)
    prompts_seen: set[str] = field(default_factory=set)
    providers_seen: set[str] = field(default_factory=set)
    first_rank_per_run: dict[int, int] = field(default_factory=dict)
    mentions: int = 0
    first_mentions: int = 0
    citations: int = 0
    citation_quality_per_run: dict[int, float] = field(default_factory=dict)
    # provider → [k_appeared, n_captures]
    provider_kn: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    # per scored run where the brand appeared: (rank, compound, mention_type)
    sentiment_points: list[tuple[int, float, str | None]] = field(default_factory=list)


def load_config() -> ScoringConfig:
    """Resolve the active scoring config.

    Reads the most recent row from the scoring_configs table when that model
    exists and has a row; otherwise returns the built-in v2 defaults. The table
    is introduced in a later phase, so today this always falls back to defaults.
    """
    try:
        from backend.models import ScoringConfigRow  # noqa: PLC0415
    except Exception:
        return ScoringConfig()
    try:
        with session_scope() as db:
            row = db.scalars(
                select(ScoringConfigRow).order_by(ScoringConfigRow.version.desc())
            ).first()
    except Exception:
        return ScoringConfig()
    if row is None:
        return ScoringConfig()

    cfg = ScoringConfig(version=row.version)
    blob = row.weights or {}
    for comp, key in (
        ("presence", "w_presence"), ("position", "w_position"),
        ("citation", "w_citation"), ("sentiment", "w_sentiment"),
        ("sov", "w_sov"), ("provider", "w_provider"),
    ):
        if key in blob:
            cfg.weights[comp] = float(blob[key])
    if "gamma" in blob:
        cfg.gamma = float(blob["gamma"])
    if "n_target" in blob:
        cfg.n_target = int(blob["n_target"])
    return cfg


class ScoringEngine:
    """Computes GEO scores for every brand in a project from processed runs."""

    def __init__(self, project_id: int, config: ScoringConfig | None = None):
        self.project_id = project_id
        self.config = config or load_config()

    def compute(self) -> dict[str, Any]:
        with session_scope() as db:
            project = db.get(Project, self.project_id)
            if project is None:
                return {}
            runs: list[Run] = list(
                db.scalars(select(Run).where(Run.project_id == self.project_id)).all()
            )
            competitors = list(
                db.scalars(
                    select(Competitor).where(Competitor.project_id == self.project_id)
                ).all()
            )
            scored = [r for r in runs if r.status == _SCORED_STATUS]
            failed = [r for r in runs if r.status == "error"]
            n = len(scored)
            attempted = n + len(failed)
            capture_failure_rate = (len(failed) / attempted) if attempted else 0.0
            n_effective = n * (1 - capture_failure_rate)

            raw, target_name, provider_totals = self._scan(scored)

            # P6 denominator: each provider's TOTAL run count, applied to every
            # brand (k stays per-brand). Done after the scan so brands discovered
            # mid-dataset aren't undercounted, and absent-on-a-provider counts as
            # 0/n there, correctly lowering provider authority.
            for r in raw.values():
                for prov, totals in provider_totals.items():
                    r.provider_kn[prov][1] = totals["runs"]

            total_brand_mentions = sum(r.mentions for r in raw.values())
            sov_available = len(competitors) >= 2 and total_brand_mentions > 0

            rows: list[BrandScore] = []
            for name, r in raw.items():
                rows.append(
                    self._score_brand(
                        r,
                        is_target=(name == target_name),
                        n=n,
                        n_effective=n_effective,
                        total_brand_mentions=total_brand_mentions,
                        sov_available=sov_available,
                    )
                )
            rows.sort(key=lambda b: b.geo_final, reverse=True)

            reliability = (1 - capture_failure_rate) * C.confidence_scalar(n, self.config.n_target)
            target_row = next((b for b in rows if b.is_target), None)
            provider_errors: dict[str, int] = defaultdict(int)
            for r in failed:
                provider_errors[r.provider] += 1

            return {
                "project_id": self.project_id,
                "formula_version": self.config.version,
                "total_prompts": len({r.prompt for r in runs}),
                "total_runs": len(runs),
                "n_scored": n,
                "capture_failure_rate": round(capture_failure_rate, 4),
                "reliability_score": round(reliability, 4),
                "reliability_tier": C.reliability_tier(reliability),
                "sov_available": sov_available,
                "target": target_row.to_row() if target_row else None,
                "brands": [b.to_row() for b in rows],
                "providers": self._provider_summary(provider_totals, provider_errors),
            }

    # ---- internals ----

    def _scan(
        self, scored: list[Run]
    ) -> tuple[dict[str, _Raw], str | None, dict[str, dict[str, int]]]:
        """Single pass over processed runs → per-brand accumulators."""
        raw: dict[str, _Raw] = {}
        target_name: str | None = None
        provider_totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"runs": 0, "with_target": 0, "citations": 0}
        )

        def acc(name: str) -> _Raw:
            if name not in raw:
                raw[name] = _Raw(name=name)
            return raw[name]

        for run in scored:
            provider_totals[run.provider]["runs"] += 1
            provider_totals[run.provider]["citations"] += len(run.citations)

            # brand → first (lowest) rank in this run
            first_rank: dict[str, int] = {}
            for m in run.mentions:
                name = m.normalized_entity
                r = acc(name)
                r.mentions += 1
                if m.is_target:
                    target_name = name
                rank = m.mention_position or 0
                if name not in first_rank or (rank and rank < first_rank[name]):
                    first_rank[name] = rank

            for name, rank in first_rank.items():
                r = acc(name)
                r.appeared_run_ids.add(run.id)
                r.prompts_seen.add(run.prompt)
                r.providers_seen.add(run.provider)
                r.first_rank_per_run[run.id] = rank
                if rank == 1:
                    r.first_mentions += 1

            # provider per-brand appearances (k only); the n denominator is set
            # to each provider's total run count after the scan (see compute).
            for name in first_rank:
                raw[name].provider_kn[run.provider][0] += 1

            # citations → attribute to a brand by domain-root match (quality 1.0 for now)
            for c in run.citations:
                root = brand_root_from_domain(c.domain)
                for name in raw:
                    if brand_root_from_domain(name) == root or name.lower() == root:
                        raw[name].citations += 1
                        raw[name].citation_quality_per_run[run.id] = max(
                            raw[name].citation_quality_per_run.get(run.id, 0.0), 1.0
                        )
                        break

            # sentiment (target only — run-level field), weighted by target rank
            if target_name and target_name in first_rank:
                compound = _SENT.get(run.target_sentiment or "neutral", 0.0)
                mtype = "negative_example" if run.target_framing == "cautionary" else None
                acc(target_name).sentiment_points.append(
                    (first_rank[target_name], compound, mtype)
                )
                provider_totals[run.provider]["with_target"] += 1

        return raw, target_name, provider_totals

    def _score_brand(
        self,
        r: _Raw,
        *,
        is_target: bool,
        n: int,
        n_effective: float,
        total_brand_mentions: int,
        sov_available: bool,
    ) -> BrandScore:
        cfg = self.config
        k = len(r.appeared_run_ids)

        # P1 Presence — Bayesian for sparse data, Wilson otherwise
        if n < cfg.bayesian_cutoff:
            p1 = C.bayesian_mean(k, n)
            method = "bayesian"
        else:
            p1 = C.wilson_midpoint(k, n)
            method = "wilson"
        ci_lower, ci_upper = C.wilson_interval(k, n)

        # P2 Position — mean attention weight over runs where the brand appeared
        if r.first_rank_per_run:
            p2 = sum(
                C.position_weight(rank, cfg.gamma) for rank in r.first_rank_per_run.values()
            ) / len(r.first_rank_per_run)
        else:
            p2 = 0.0

        # P3 Citation — quality-weighted citation mass over n captures (Wilson)
        cit_mass = sum(r.citation_quality_per_run.values())
        p3 = C.wilson_midpoint(cit_mass, n)

        # P4 Sentiment — position-weighted, mention-type-modified, normalized to [0,1]
        if r.sentiment_points:
            num = 0.0
            den = 0.0
            for rank, compound, mtype in r.sentiment_points:
                w = C.position_weight(rank, cfg.gamma)
                adj = compound * mention_type_weight(mtype)
                num += adj * w
                den += w
            p4 = C.normalize_sentiment(num / den) if den else 0.5
        else:
            p4 = 0.5  # neutral midpoint (not penalized)

        # P5 Share of Voice
        p5: float | None = (
            (r.mentions / total_brand_mentions) if sov_available and total_brand_mentions else None
        )

        # P6 Provider authority — provider-weighted presence rate
        num_p = 0.0
        den_p = 0.0
        for prov, (kp, np_) in r.provider_kn.items():
            if np_ <= 0:
                continue
            w = provider_weight(prov)
            num_p += w * C.wilson_midpoint(kp, np_)
            den_p += w
        p6 = (num_p / den_p) if den_p else 0.0

        # Composite
        weights = cfg.effective_weights(sov_available=sov_available)
        geo_raw = (
            weights["presence"] * p1
            + weights["position"] * p2
            + weights["citation"] * p3
            + weights["sentiment"] * p4
            + weights["sov"] * (p5 or 0.0)
            + weights["provider"] * p6
        )
        scalar = C.confidence_scalar(n_effective, cfg.n_target)
        geo_adjusted = geo_raw * scalar
        geo_final = round(geo_adjusted * 100, 1)

        return BrandScore(
            brand=r.name,
            is_target=is_target,
            presence=round(p1, 4),
            position=round(p2, 4),
            citation=round(p3, 4),
            sentiment=round(p4, 4),
            sov=(round(p5, 4) if p5 is not None else None),
            provider=round(p6, 4),
            geo_raw=round(geo_raw, 4),
            confidence_scalar=round(scalar, 4),
            geo_adjusted=round(geo_adjusted, 4),
            geo_final=geo_final,
            wilson_ci_lower=round(ci_lower, 4),
            wilson_ci_upper=round(ci_upper, 4),
            confidence_level=C.confidence_tier(ci_upper - ci_lower),
            estimation_method=method,
            sov_available=(p5 is not None),
            n_captures=n,
            n_appeared=k,
            mentions=r.mentions,
            prompts_appeared_in=len(r.prompts_seen),
            providers=sorted(r.providers_seen),
            avg_position=(
                round(sum(r.first_rank_per_run.values()) / len(r.first_rank_per_run), 2)
                if r.first_rank_per_run else None
            ),
            first_mentions=r.first_mentions,
            citations=r.citations,
        )

    @staticmethod
    def _provider_summary(
        provider_totals: dict[str, dict[str, int]], provider_errors: dict[str, int]
    ) -> list[dict[str, Any]]:
        # union of providers seen in scored runs and in failed runs
        names = set(provider_totals) | set(provider_errors)
        out = []
        for p in sorted(names):
            d = provider_totals.get(p, {"runs": 0, "with_target": 0, "citations": 0})
            out.append({
                "provider": p,
                "runs": d["runs"],
                "errors": provider_errors.get(p, 0),
                "with_target": d["with_target"],
                "citations": d["citations"],
                "target_share": round((d["with_target"] / d["runs"]) * 100, 2) if d["runs"] else 0.0,
            })
        return out


def compute_project_scores(project_id: int) -> dict[str, Any]:
    """Entry point: compute the GEO scores for every brand in a project."""
    return ScoringEngine(project_id).compute()
