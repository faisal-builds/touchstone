"""Resilience primitives for the inline plane.

Inline means the plane's failure is the customer's failure, so availability and
graceful degradation are first-class. These are the mechanisms (not the live
hardening) behind the plane's multi-region/SLO posture:

* ``Bulkhead`` — bounds concurrent in-flight verifications (backpressure); when
  saturated the caller degrades per fail mode rather than queueing unboundedly.
* ``CircuitBreaker`` — sheds a tier that is failing repeatedly, with a half-open
  probe, so one bad dependency does not stall the hot path.
* ``LatencyBudget`` — tracks remaining wall-clock so the executor can bound each
  step and never blow the caller's budget.
* ``fail_action`` — maps a fail mode to the safe default action.
"""

from __future__ import annotations

import time

from .schemas import Action


class BulkheadFull(Exception):
    """Raised when no concurrency slot is available (backpressure signal)."""


class Bulkhead:
    """A simple counting semaphore with non-blocking acquire.

    Unlike asyncio.Semaphore we never await on a full bulkhead — inline calls must
    fail fast (and degrade) rather than queue, so latency stays bounded.
    """

    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    def acquire(self) -> None:
        if self._inflight >= self._limit:
            raise BulkheadFull(f"bulkhead full ({self._limit})")
        self._inflight += 1

    def release(self) -> None:
        if self._inflight > 0:
            self._inflight -= 1

    def __enter__(self) -> Bulkhead:
        self.acquire()
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False


class CircuitBreaker:
    """Trips open after ``failure_threshold`` consecutive failures, then probes.

    States: closed (normal) → open (shed, fail fast) → half-open (one probe). A
    success in half-open closes it; a failure re-opens it.
    """

    def __init__(self, *, failure_threshold: int, reset_seconds: float,
                 clock=time.monotonic) -> None:
        self._threshold = max(1, failure_threshold)
        self._reset = reset_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self._reset:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """Whether a call may proceed right now."""
        return self.state != "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        if self.state == "half_open":
            # Probe failed — re-open immediately.
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class LatencyBudget:
    """Tracks remaining wall-clock against a deadline."""

    def __init__(self, budget_ms: float, clock=time.monotonic) -> None:
        self._clock = clock
        self._deadline = clock() + budget_ms / 1000.0
        self._start = clock()

    def remaining_s(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def expired(self) -> bool:
        return self._clock() >= self._deadline

    def elapsed_ms(self) -> float:
        return (self._clock() - self._start) * 1000.0


def fail_action(fail_mode: str) -> Action:
    """The safe default action when the plane cannot reach a verdict."""
    return Action.BLOCK if str(fail_mode).lower() == "closed" else Action.ALLOW
