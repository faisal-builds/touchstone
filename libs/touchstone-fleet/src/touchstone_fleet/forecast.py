"""Capacity forecasting + resource optimization.

Turns a history of demand (QPS, latency, queue depth) into a forward projection
and a concrete resource recommendation: how many workers / how large a warm pool
to hold to serve forecast demand at a target utilization with headroom. Forecasts
use exponential smoothing and Holt's linear trend (transparent and explainable —
capacity decisions must be auditable, not opaque).

The math is real and tested. Its *accuracy* depends on real demand history under
real traffic; fed synthetic series it projects the series, not the business.
"""

from __future__ import annotations

import dataclasses
import math


def ewma(series: list[float], alpha: float = 0.3) -> float:
    """Exponentially-weighted moving average (the smoothed current level)."""
    if not series:
        return 0.0
    level = series[0]
    for x in series[1:]:
        level = alpha * x + (1 - alpha) * level
    return level


def holt_forecast(series: list[float], *, alpha: float = 0.5, beta: float = 0.3,
                  horizon: int = 1) -> float:
    """Holt's linear trend forecast ``horizon`` steps ahead.

    Returns a non-negative projection (demand cannot be negative).
    """
    if not series:
        return 0.0
    if len(series) == 1:
        return max(0.0, series[0])
    level = series[0]
    trend = series[1] - series[0]
    for x in series[1:]:
        prev_level = level
        level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return max(0.0, level + horizon * trend)


@dataclasses.dataclass(frozen=True)
class CapacityRecommendation:
    predicted_demand: float       # forecast units (e.g. QPS)
    required_units: int           # workers / pool slots to provision
    rationale: str


class CapacityPlanner:
    """Recommends provisioning from a demand forecast, a per-unit service rate, a
    target utilization, and a safety headroom multiplier."""

    def __init__(self, *, per_unit_capacity: float, target_utilization: float = 0.7,
                 headroom: float = 1.2, min_units: int = 1) -> None:
        if per_unit_capacity <= 0:
            raise ValueError("per_unit_capacity must be positive")
        if not (0 < target_utilization <= 1):
            raise ValueError("target_utilization must be in (0, 1]")
        self._cap = per_unit_capacity
        self._util = target_utilization
        self._headroom = headroom
        self._min = min_units

    def recommend(self, demand_series: list[float], *, horizon: int = 1) -> CapacityRecommendation:
        predicted = holt_forecast(demand_series, horizon=horizon)
        effective_per_unit = self._cap * self._util
        raw = (predicted * self._headroom) / effective_per_unit if effective_per_unit else 0.0
        units = max(self._min, math.ceil(raw))
        return CapacityRecommendation(
            predicted_demand=round(predicted, 4),
            required_units=units,
            rationale=(
                f"forecast≈{predicted:.1f}/unit-time × {self._headroom:g} headroom ÷ "
                f"({self._cap:g} × {self._util:g} util) ⇒ {units} units"
            ),
        )
