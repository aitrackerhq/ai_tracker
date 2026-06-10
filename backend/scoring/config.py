"""Scoring configuration — weights and tunables for the composite GEO score.

These are the `formula_version = 2` defaults. They can later be overridden per
version from the `scoring_configs` DB table (see engine.load_config); the values
here are the seed/fallback so scoring works before any row exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FORMULA_VERSION = 2

# Component weights — must sum to 1.0.
DEFAULT_WEIGHTS = {
    "presence": 0.30,   # P1
    "position": 0.20,   # P2
    "citation": 0.15,   # P3
    "sentiment": 0.15,  # P4
    "sov": 0.10,        # P5 (renormalized away when unavailable)
    "provider": 0.10,   # P6
}

# When SOV (P5) is unavailable (<2 competitors), its weight is redistributed to
# the components most correlated with what it measures.
SOV_REDISTRIBUTION = {"presence": 0.06, "position": 0.04}

GAMMA = 0.75          # position-decay exponent: position_weight(r) = 1/r^GAMMA
N_TARGET = 100        # sample size at which full confidence is granted
BAYESIAN_CUTOFF = 10  # use Bayesian estimator below this many captures, Wilson at/above
MIN_DISPLAY_CONFIDENCE = 0.30  # below this confidence_scalar, show "insufficient data"

# EMA smoothing factor by capture cadence.
EMA_ALPHA = {"daily": 0.30, "weekly": 0.50, "monthly": 0.70}

# Provider commercial-intent weights for P6 (research/commercial intent of the
# user population on each surface). Unlisted providers fall back to `default`.
PROVIDER_WEIGHTS = {
    "perplexity": 1.00,
    "chatgpt": 0.90,
    "chatgpt_search": 0.90,
    "google_ai": 0.85,
    "google_ai_mode": 0.85,
    "gemini": 0.70,
    "claude_ai": 0.70,
    "copilot": 0.65,
    "grok": 0.50,
    "default": 0.50,
}

# Mention-type modifier applied to sentiment before normalization (P4).
MENTION_TYPE_WEIGHTS = {
    "primary_rec": 1.0,
    "comparison": 0.8,
    "secondary_mention": 0.6,
    "incidental": 0.3,
    "negative_example": 0.0,  # forced negative regardless of model output
}
DEFAULT_MENTION_TYPE = "primary_rec"

# Sentiment label → compound score in [-1, 1] (run-level fallback when a
# per-mention compound score isn't available).
SENTIMENT_LABEL_COMPOUND = {
    "positive": 0.6,
    "neutral": 0.0,
    "negative": -0.6,
    "not-mentioned": 0.0,
}


def provider_weight(provider: str) -> float:
    """Commercial-intent weight for a provider, falling back to the default."""
    return PROVIDER_WEIGHTS.get(provider, PROVIDER_WEIGHTS["default"])


def mention_type_weight(mention_type: str | None) -> float:
    """Sentiment modifier for a mention type, falling back to the default."""
    if mention_type is None:
        return MENTION_TYPE_WEIGHTS[DEFAULT_MENTION_TYPE]
    return MENTION_TYPE_WEIGHTS.get(mention_type, MENTION_TYPE_WEIGHTS[DEFAULT_MENTION_TYPE])


@dataclass
class ScoringConfig:
    """Resolved scoring configuration for one computation."""

    version: int = FORMULA_VERSION
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    gamma: float = GAMMA
    n_target: int = N_TARGET
    bayesian_cutoff: int = BAYESIAN_CUTOFF
    min_display_confidence: float = MIN_DISPLAY_CONFIDENCE

    def effective_weights(self, *, sov_available: bool) -> dict[str, float]:
        """Weights to use for this computation, redistributing SOV when unavailable.

        Always sums to 1.0 by construction so unavailable components never deflate
        the score.
        """
        w = dict(self.weights)
        if not sov_available:
            sov_w = w.pop("sov", 0.0)
            w["sov"] = 0.0
            total_redist = sum(SOV_REDISTRIBUTION.values())
            for comp, share in SOV_REDISTRIBUTION.items():
                w[comp] = w.get(comp, 0.0) + sov_w * (share / total_redist)
        return w
