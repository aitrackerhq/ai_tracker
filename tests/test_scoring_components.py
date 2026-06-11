"""Unit tests for the deterministic scoring primitives (issue #9).

These assert the exact values from the scoring spec so the math can't silently
drift, plus the determinism / monotonicity properties the issue requires.
"""
import pytest

from backend.scoring import components as C
from backend.scoring.config import ScoringConfig


# ---- Wilson presence ----

@pytest.mark.parametrize("k,n,expected", [
    (1, 1, 0.603),   # (1 + z²/2)/(1 + z²) = 2.9208/4.8416 (spec's 0.611 is an arithmetic slip)
    (5, 5, 0.783),
    (100, 100, 0.982),
    (0, 0, 0.5),     # no data → prior
])
def test_wilson_midpoint(k, n, expected):
    assert C.wilson_midpoint(k, n) == pytest.approx(expected, abs=1e-3)


def test_wilson_midpoint_never_reaches_one_on_small_samples():
    # 1/1 must NOT score a perfect 1.0 (the old formula's bug)
    assert C.wilson_midpoint(1, 1) < 0.7


def test_wilson_interval_width_shrinks_with_n():
    lo_s, hi_s = C.wilson_interval(5, 5)
    lo_l, hi_l = C.wilson_interval(100, 100)
    assert (hi_s - lo_s) > (hi_l - lo_l)  # more data → tighter interval


def test_wilson_interval_no_data():
    assert C.wilson_interval(0, 0) == (0.0, 1.0)


# ---- position decay ----

@pytest.mark.parametrize("rank,expected", [
    (1, 1.000), (2, 0.595), (3, 0.438), (4, 0.354), (5, 0.299),
    (10, 0.178), (20, 0.106), (28, 0.082),
])
def test_position_weight(rank, expected):
    assert C.position_weight(rank) == pytest.approx(expected, abs=1e-3)


def test_position_weight_monotonic_decreasing():
    ws = [C.position_weight(r) for r in range(1, 30)]
    assert all(ws[i] > ws[i + 1] for i in range(len(ws) - 1))


def test_position_weight_zero_for_absent():
    assert C.position_weight(0) == 0.0


# ---- confidence scalar ----

@pytest.mark.parametrize("n,expected", [
    (5, 0.224), (10, 0.316), (25, 0.500), (50, 0.707), (100, 1.000),
])
def test_confidence_scalar(n, expected):
    assert C.confidence_scalar(n) == pytest.approx(expected, abs=1e-3)


def test_confidence_scalar_capped_at_one():
    assert C.confidence_scalar(500) == 1.0


# ---- bayesian ----

@pytest.mark.parametrize("k,n,expected", [
    (0, 0, 0.50), (0, 1, 0.40), (1, 1, 0.60), (8, 10, 0.714), (40, 50, 0.778),
])
def test_bayesian_mean(k, n, expected):
    assert C.bayesian_mean(k, n) == pytest.approx(expected, abs=1e-3)


# ---- sentiment normalization ----

def test_normalize_sentiment():
    assert C.normalize_sentiment(-1.0) == 0.0
    assert C.normalize_sentiment(0.0) == 0.5
    assert C.normalize_sentiment(1.0) == 1.0


# ---- EMA ----

def test_ema_seeds_on_first_observation():
    assert C.ema(0.8, None, 0.3) == 0.8


def test_ema_converges_to_constant():
    val = 0.2
    for _ in range(200):
        val = C.ema(0.8, val, 0.3)
    assert val == pytest.approx(0.8, abs=1e-3)


# ---- significance ----

def test_significance_no_change_is_zero():
    assert C.significance_z(50, 100, 50, 100) == pytest.approx(0.0)


def test_significance_label_thresholds():
    assert C.significance_label(0.5) == "no_change"
    assert C.significance_label(1.7) == "possible"
    assert C.significance_label(2.0) == "significant"
    assert C.significance_label(3.0) == "highly_significant"
    assert C.significance_label(None) == "no_data"


def test_significance_empty_sample():
    assert C.significance_z(0, 0, 1, 10) is None


# ---- weight renormalization ----

def test_weights_sum_to_one_with_sov():
    w = ScoringConfig().effective_weights(sov_available=True)
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["sov"] == pytest.approx(0.10)


def test_weights_sum_to_one_without_sov_and_redistribute():
    w = ScoringConfig().effective_weights(sov_available=False)
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["sov"] == 0.0
    # the 0.10 SOV weight goes to presence (+0.06) and position (+0.04)
    assert w["presence"] == pytest.approx(0.36)
    assert w["position"] == pytest.approx(0.24)


# ---- tier helpers ----

def test_confidence_tier_boundaries():
    assert C.confidence_tier(0.10) == "high"
    assert C.confidence_tier(0.25) == "good"
    assert C.confidence_tier(0.35) == "moderate"
    assert C.confidence_tier(0.50) == "low"
    assert C.confidence_tier(0.60) == "insufficient"


def test_reliability_tier_boundaries():
    assert C.reliability_tier(0.90) == "reliable"
    assert C.reliability_tier(0.70) == "mostly_reliable"
    assert C.reliability_tier(0.50) == "limited"
    assert C.reliability_tier(0.30) == "unreliable"
