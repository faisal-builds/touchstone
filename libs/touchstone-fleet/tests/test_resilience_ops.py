"""Chaos framework, SLO/error-budget math, and capacity forecasting."""

from __future__ import annotations

import random

import pytest

from touchstone_fleet import (
    SLO,
    CapacityPlanner,
    ChaosRunner,
    ChaosScenario,
    ChaosStep,
    FaultInjector,
    InjectedFault,
    SLOTracker,
    ewma,
    holt_forecast,
    multi_window_burn_alert,
)

# --- chaos -----------------------------------------------------------------


def test_failpoint_is_noop_until_armed():
    inj = FaultInjector()
    inj.failpoint("fast_tier")  # no raise
    assert inj.latency("fast_tier") == 0.0


def test_armed_error_failpoint_raises():
    inj = FaultInjector()
    inj.arm("fast_tier", error=True)
    with pytest.raises(InjectedFault):
        inj.failpoint("fast_tier")


def test_latency_injection_returns_delay():
    inj = FaultInjector()
    inj.arm("route", latency_s=0.25)
    assert inj.latency("route") == 0.25


def test_probability_gating_is_deterministic_with_seed():
    inj = FaultInjector(rng=random.Random(0))
    inj.arm("flaky", error=True, probability=0.5)
    fires = 0
    for _ in range(200):
        try:
            inj.failpoint("flaky")
        except InjectedFault:
            fires += 1
    assert 70 <= fires <= 130  # ~50% with seeded RNG


def test_max_fires_auto_disarms():
    inj = FaultInjector()
    inj.arm("once", error=True, max_fires=1)
    with pytest.raises(InjectedFault):
        inj.failpoint("once")
    inj.failpoint("once")  # auto-disarmed -> no raise
    assert not inj.armed("once")


async def test_chaos_runner_applies_and_clears():
    inj = FaultInjector()

    async def probe():
        return inj.armed("region_down")

    scenario = ChaosScenario("region outage", [
        ChaosStep("baseline"),
        ChaosStep("arm", arm={"name": "region_down", "drop": True}),
        ChaosStep("recover", disarm="region_down"),
    ])
    results = await ChaosRunner(inj).run(scenario, probe)
    assert [r for _, r in results] == [False, True, False]
    assert not inj.armed("region_down")  # cleared on exit

# --- SLO -------------------------------------------------------------------


def test_slo_attainment_and_error_budget():
    t = SLOTracker(SLO("inline-latency", objective=0.99, latency_threshold_s=0.15))
    for _ in range(99):
        t.record(latency_s=0.05)   # good
    t.record(latency_s=0.50)       # bad
    assert t.attainment() == pytest.approx(0.99)
    # Exactly on budget (1% bad, 1% budget) -> ~0 remaining, burn rate ~1.
    assert t.error_budget_remaining() == pytest.approx(0.0, abs=1e-9)
    assert t.burn_rate() == pytest.approx(1.0, abs=1e-9)


def test_slo_budget_blown_is_negative():
    t = SLOTracker(SLO("avail", objective=0.99))
    for _ in range(90):
        t.record(good=True)
    for _ in range(10):
        t.record(good=False)   # 10% bad vs 1% budget
    assert t.error_budget_remaining() < 0
    assert t.burn_rate() > 1.0


def test_multi_window_burn_alert_requires_both():
    fast = SLOTracker(SLO("x", objective=0.999))
    slow = SLOTracker(SLO("x", objective=0.999))
    for _ in range(100):
        fast.record(good=False)   # fast window burning hard
    for _ in range(100):
        slow.record(good=True)    # slow window healthy
    assert multi_window_burn_alert(fast, slow) is False
    for _ in range(100):
        slow.record(good=False)
    assert multi_window_burn_alert(fast, slow) is True

# --- forecasting -----------------------------------------------------------


def test_ewma_tracks_level():
    assert ewma([10, 10, 10]) == pytest.approx(10.0)
    assert ewma([0, 10], alpha=0.5) == pytest.approx(5.0)


def test_holt_projects_upward_trend():
    rising = [10, 20, 30, 40, 50]
    f = holt_forecast(rising, horizon=1)
    assert f > 50  # trend continues upward


def test_capacity_planner_recommends_units():
    planner = CapacityPlanner(per_unit_capacity=100.0, target_utilization=0.7, headroom=1.2)
    rec = planner.recommend([100, 200, 300, 400], horizon=1)
    assert rec.predicted_demand > 400
    assert rec.required_units >= 1
    assert "headroom" in rec.rationale
