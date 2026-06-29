"""Robustness-scoring unit tests: Wilson CI, comparison, regression, trend."""

import pytest

from touchstone_rhd.scoring.robustness import RobustnessScorer

S = RobustnessScorer()


def test_no_exploits_is_full_robustness():
    r = S.score(executed=100, exploits=0)
    assert r.robustness == 1.0
    assert r.ci.high == 1.0
    assert r.ci.low < 1.0  # finite sample -> lower bound below 1


def test_all_exploits_is_zero_robustness():
    r = S.score(executed=100, exploits=100)
    assert r.robustness == 0.0
    assert r.ci.low == 0.0


def test_half_exploits():
    r = S.score(executed=100, exploits=50)
    assert r.robustness == pytest.approx(0.5)
    assert r.ci.low < 0.5 < r.ci.high


def test_ci_narrows_with_more_samples():
    small = S.score(executed=10, exploits=1)
    large = S.score(executed=1000, exploits=100)
    assert (small.ci.high - small.ci.low) > (large.ci.high - large.ci.low)


def test_zero_executed_is_unknown_wide_ci():
    r = S.score(executed=0, exploits=0)
    assert r.ci.low == 0.0 and r.ci.high == 1.0


def test_regression_detected_on_meaningful_drop():
    old = S.score(executed=500, exploits=5)    # ~0.99
    new = S.score(executed=500, exploits=150)  # ~0.70
    cmp = S.compare(old, new)
    assert cmp.is_regression
    assert cmp.delta < 0
    assert not cmp.is_improvement


def test_noise_is_not_a_regression():
    old = S.score(executed=500, exploits=50)
    new = S.score(executed=500, exploits=52)
    cmp = S.compare(old, new)
    assert not cmp.is_regression


def test_improvement_detected():
    old = S.score(executed=500, exploits=150)
    new = S.score(executed=500, exploits=5)
    cmp = S.compare(old, new)
    assert cmp.is_improvement
    assert not cmp.is_regression


def test_trend_directions():
    assert S.trend([0.5, 0.55, 0.7, 0.8]) == "improving"
    assert S.trend([0.9, 0.85, 0.7, 0.6]) == "declining"
    assert S.trend([0.8, 0.81, 0.79, 0.8]) == "stable"
    assert S.trend([0.8]) == "insufficient_data"


def test_weighted_score_penalizes_severity():
    from touchstone_rhd.domain.models import Severity
    # Same exploit count, different severities => critical is penalized more.
    crit = S.weighted_score(executed=100, severities=[Severity.CRITICAL] * 10)
    low = S.weighted_score(executed=100, severities=[Severity.LOW] * 10)
    assert crit < low
    # Critical weight is 1.0, so 10/100 => 0.9 robustness.
    assert crit == pytest.approx(0.9)
    # Low weight is 0.2, so 10*0.2/100 => 0.98 robustness.
    assert low == pytest.approx(0.98)


def test_weighted_score_no_exploits_is_one():
    from touchstone_rhd.domain.models import Severity
    assert S.weighted_score(executed=50, severities=[]) == 1.0
    assert S.weighted_score(executed=0, severities=[Severity.CRITICAL]) == 1.0


def test_weighted_score_clamps_at_zero():
    from touchstone_rhd.domain.models import Severity
    # More critical exploits than executed (degenerate) clamps to 0, never negative.
    assert S.weighted_score(executed=2, severities=[Severity.CRITICAL] * 5) == 0.0
