"""Pure statistical primitives for the GEO scoring system.

Every function here is a deterministic pure function of its inputs — no DB, no
clock, no randomness. This is what makes the component scores reproducible for
the same dataset (issue #9). The DB-aware orchestration lives in engine.py.

References:
- Wilson score interval: small-sample proportion estimator (Reddit ranking, A/B testing).
- Position decay 1/r^gamma: attention-in-ranked-lists research (Joachims 2005, Craswell 2008).
"""
from __future__ import annotations

import math

Z_95 = 1.96  # z for a 95% confidence level


def wilson_midpoint(k: float, n: float, z: float = Z_95) -> float:
    """Bias-corrected proportion estimate: (k + z²/2) / (n + z²).

    Shrinks extreme small-sample rates toward 0.5. At n=0 returns 0.5 (prior).
    `k` may be fractional (e.g. quality-weighted citation mass).
    """
    if n <= 0:
        return 0.5
    z2 = z * z
    return (k + z2 / 2) / (n + z2)


def wilson_interval(k: float, n: float, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson confidence interval (lower, upper) for a k/n proportion.

    Returns (0.0, 1.0) when n=0 (maximal uncertainty).
    """
    if n <= 0:
        return (0.0, 1.0)
    z2 = z * z
    centre = k + z2 / 2
    margin = z * math.sqrt(k * (n - k) / n + z2 / 4)
    lower = (centre - margin) / (n + z2)
    upper = (centre + margin) / (n + z2)
    return (max(0.0, lower), min(1.0, upper))


def bayesian_mean(k: float, n: float, alpha: float = 2.0, beta: float = 2.0) -> float:
    """Beta-Binomial posterior mean (k+alpha)/(n+alpha+beta). Used for n<10 sparse data.

    Beta(2,2) is a weak symmetric prior (mean 0.5) that pulls extremes to centre.
    """
    return (k + alpha) / (n + alpha + beta)


def position_weight(rank: int, gamma: float = 0.75) -> float:
    """Attention decay for a 1-indexed rank: 1 / rank^gamma. rank<=0 → 0.0."""
    if rank <= 0:
        return 0.0
    return 1.0 / (rank ** gamma)


def confidence_scalar(n_effective: float, n_target: int = 100) -> float:
    """sqrt(n_eff / n_target) capped at 1.0 — discounts scores from small samples."""
    if n_effective <= 0 or n_target <= 0:
        return 0.0
    return min(1.0, math.sqrt(n_effective / n_target))


def normalize_sentiment(compound: float) -> float:
    """Map a sentiment compound score from [-1, 1] to [0, 1]."""
    return max(0.0, min(1.0, (compound + 1.0) / 2.0))


def ema(raw: float, previous: float | None, alpha: float) -> float:
    """Exponential moving average. First observation (previous=None) seeds the baseline.

    NOTE: path-dependent by design — the smoothed value is NOT reproducible from a
    single dataset. Determinism is preserved on the raw components / GEO_raw, which
    are stored separately; this is only the display-smoothing layer.
    """
    if previous is None:
        return raw
    return alpha * raw + (1.0 - alpha) * previous


def significance_z(k1: int, n1: int, k2: int, n2: int) -> float | None:
    """Two-proportion z-test statistic for period-over-period appearance-rate change.

    Returns None when either sample is empty or the pooled proportion is degenerate.
    """
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    return (p1 - p2) / se


def significance_label(z: float | None) -> str:
    """Human-readable significance tier for a z statistic (|z| thresholds)."""
    if z is None:
        return "no_data"
    az = abs(z)
    if az >= 2.576:
        return "highly_significant"
    if az >= 1.960:
        return "significant"
    if az >= 1.645:
        return "possible"
    return "no_change"


def confidence_tier(ci_width: float) -> str:
    """Map a Wilson CI width to a human-readable confidence tier."""
    if ci_width < 0.20:
        return "high"
    if ci_width < 0.30:
        return "good"
    if ci_width < 0.40:
        return "moderate"
    if ci_width < 0.55:
        return "low"
    return "insufficient"


def reliability_tier(score: float) -> str:
    """Map a reliability score [0,1] to an operational-health tier."""
    if score > 0.85:
        return "reliable"
    if score >= 0.65:
        return "mostly_reliable"
    if score >= 0.40:
        return "limited"
    return "unreliable"
