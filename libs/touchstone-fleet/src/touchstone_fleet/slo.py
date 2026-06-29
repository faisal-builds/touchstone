"""SLO layer — objectives, error budgets, and burn-rate alerting.

The observability primitive an inline platform is judged on: define an objective
(e.g. 99.9% of decisions under the latency budget), track good-vs-total events,
and compute the **error budget** and its **burn rate**. Multi-window burn-rate
alerting (a fast window catches acute outages, a slow window catches steady
erosion) is the Google-SRE pattern and is what an on-call rotation would page on.

This computes the numbers correctly from whatever events it is fed. The events
themselves — real decision latencies, real availability under real traffic — are
a production input; feeding it synthetic events (as the tests do) exercises the
math, not the system's true reliability.
"""

from __future__ import annotations

import collections
import dataclasses


@dataclasses.dataclass(frozen=True)
class SLO:
    name: str
    objective: float                  # e.g. 0.999 == 99.9% good
    latency_threshold_s: float | None = None  # if set, "good" == latency <= threshold

    @property
    def budget(self) -> float:
        """The allowed bad fraction (1 - objective)."""
        return max(0.0, 1.0 - self.objective)


class SLOTracker:
    """Counter-based SLO tracker over a bounded rolling window of recent events."""

    def __init__(self, slo: SLO, *, window: int = 10_000) -> None:
        self._slo = slo
        self._events: collections.deque[bool] = collections.deque(maxlen=window)

    @property
    def slo(self) -> SLO:
        return self._slo

    def record(self, *, good: bool | None = None, latency_s: float | None = None) -> None:
        if good is None:
            if latency_s is None or self._slo.latency_threshold_s is None:
                raise ValueError("record needs good= or (latency_s= with a latency SLO)")
            good = latency_s <= self._slo.latency_threshold_s
        self._events.append(bool(good))

    @property
    def total(self) -> int:
        return len(self._events)

    def attainment(self) -> float:
        if not self._events:
            return 1.0
        return sum(self._events) / len(self._events)

    def bad_fraction(self) -> float:
        return 1.0 - self.attainment()

    def error_budget_remaining(self) -> float:
        """Fraction of the error budget left (1.0 == untouched, <0 == blown)."""
        if self._slo.budget <= 0:
            return 1.0 if self.bad_fraction() == 0 else -1.0
        return 1.0 - (self.bad_fraction() / self._slo.budget)

    def burn_rate(self) -> float:
        """How fast the budget is burning: 1.0 == exactly on budget, >1 == too fast."""
        if self._slo.budget <= 0:
            return float("inf") if self.bad_fraction() > 0 else 0.0
        return self.bad_fraction() / self._slo.budget


def multi_window_burn_alert(
    fast: SLOTracker, slow: SLOTracker, *,
    fast_threshold: float = 14.4, slow_threshold: float = 6.0,
) -> bool:
    """Page when BOTH a short window and a longer window are burning too fast.

    Requiring both reduces false pages from brief blips while still catching real
    sustained burns. Defaults follow the common 1h/6h multi-burn thresholds.
    """
    return fast.burn_rate() >= fast_threshold and slow.burn_rate() >= slow_threshold
