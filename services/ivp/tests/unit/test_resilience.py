"""Resilience primitives: bulkhead, circuit breaker, latency budget, fail mode."""

from __future__ import annotations

import pytest

from touchstone_ivp.resilience import (
    Bulkhead,
    BulkheadFull,
    CircuitBreaker,
    LatencyBudget,
    fail_action,
)
from touchstone_ivp.schemas import Action


def test_bulkhead_bounds_concurrency():
    b = Bulkhead(limit=2)
    b.acquire()
    b.acquire()
    with pytest.raises(BulkheadFull):
        b.acquire()
    b.release()
    b.acquire()  # slot freed
    assert b.inflight == 2


def test_circuit_breaker_opens_and_recovers():
    clock = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=3, reset_seconds=5.0, clock=lambda: clock["t"])
    assert cb.state == "closed"
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"
    assert cb.allow() is False
    # After the reset window it half-opens to probe.
    clock["t"] = 6.0
    assert cb.state == "half_open"
    assert cb.allow() is True
    cb.record_success()
    assert cb.state == "closed"


def test_circuit_breaker_reopens_on_probe_failure():
    clock = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=1, reset_seconds=5.0, clock=lambda: clock["t"])
    cb.record_failure()
    assert cb.state == "open"
    clock["t"] = 6.0
    assert cb.state == "half_open"
    cb.record_failure()  # probe fails
    assert cb.state == "open"


def test_latency_budget_tracks_remaining():
    clock = {"t": 0.0}
    budget = LatencyBudget(100.0, clock=lambda: clock["t"])
    assert budget.remaining_s() == pytest.approx(0.1)
    clock["t"] = 0.05
    assert budget.remaining_s() == pytest.approx(0.05)
    clock["t"] = 0.2
    assert budget.expired() is True
    assert budget.remaining_s() == 0.0


def test_fail_action_mapping():
    assert fail_action("closed") is Action.BLOCK
    assert fail_action("open") is Action.ALLOW
    assert fail_action("OPEN") is Action.ALLOW
