"""Risk model unit tests — the scoring must be correct, monotonic, and explainable."""

import pytest

from touchstone_risk.scorer import RiskBand, RiskModel

M = RiskModel()


def test_perfect_pass_is_low_risk():
    a = M.assess(score=1.0, uncertainty=0.0, passed=True)
    assert a.risk_score == 0.0
    assert a.band == RiskBand.LOW


def test_confident_failure_is_high_or_critical():
    a = M.assess(score=0.0, uncertainty=0.0, passed=False)
    # failure weight 0.6 -> 0.6, but fail floor + band: 0.6 is HIGH
    assert a.risk_score >= 0.5
    assert a.band in (RiskBand.HIGH, RiskBand.CRITICAL)


def test_high_uncertainty_raises_risk_even_with_high_score():
    low_unc = M.assess(score=1.0, uncertainty=0.0, passed=True).risk_score
    high_unc = M.assess(score=1.0, uncertainty=1.0, passed=True).risk_score
    assert high_unc > low_unc
    assert high_unc == pytest.approx(0.4)  # uncertainty_weight


def test_fail_floor_applies():
    # A barely-failing run with low uncertainty would score low by formula,
    # but the fail floor forces it to at least medium.
    a = M.assess(score=0.95, uncertainty=0.0, passed=False)
    assert a.risk_score >= M.fail_floor
    assert a.band != RiskBand.LOW


def test_bands_partition_the_range():
    assert M.band_for(0.0) == RiskBand.LOW
    assert M.band_for(0.24) == RiskBand.LOW
    assert M.band_for(0.25) == RiskBand.MEDIUM
    assert M.band_for(0.49) == RiskBand.MEDIUM
    assert M.band_for(0.50) == RiskBand.HIGH
    assert M.band_for(0.74) == RiskBand.HIGH
    assert M.band_for(0.75) == RiskBand.CRITICAL
    assert M.band_for(1.0) == RiskBand.CRITICAL


def test_monotonic_in_failure():
    worse = M.assess(score=0.2, uncertainty=0.0, passed=True).risk_score
    better = M.assess(score=0.8, uncertainty=0.0, passed=True).risk_score
    assert worse > better


def test_factors_are_reported():
    a = M.assess(score=0.3, uncertainty=0.6, passed=True)
    assert a.factors["failure"] == pytest.approx(0.7)
    assert a.factors["uncertainty"] == pytest.approx(0.6)


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        RiskModel(failure_weight=0.7, uncertainty_weight=0.7)


def test_inputs_are_clamped():
    a = M.assess(score=2.0, uncertainty=-1.0, passed=True)
    assert 0.0 <= a.risk_score <= 1.0
