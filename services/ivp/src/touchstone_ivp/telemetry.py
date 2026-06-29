"""Telemetry for the inline plane.

The metrics that matter for an inline gateway: decision latency (the SLO),
decisions by action, tier hit/miss, cache hit rate, fail-open/closed fallbacks,
and backpressure rejections. Registration is idempotent so the IVP can be imported
alongside other Touchstone services in one process (e.g. cross-service tests)
without duplicate-timeseries errors.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram


def _metric(factory, name):
    try:
        return factory()
    except ValueError:
        from prometheus_client import REGISTRY
        return REGISTRY._names_to_collectors[name]


DECISION_LATENCY = _metric(
    lambda: Histogram(
        "touchstone_ivp_decision_latency_seconds",
        "End-to-end inline decision latency",
        ["action", "mode"],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.25, 0.5, 1.0),
    ),
    "touchstone_ivp_decision_latency_seconds",
)
DECISIONS = _metric(
    lambda: Counter(
        "touchstone_ivp_decisions_total",
        "Inline decisions by action",
        ["action", "mode"],
    ),
    "touchstone_ivp_decisions_total",
)
TIER_RUNS = _metric(
    lambda: Counter(
        "touchstone_ivp_tier_runs_total", "Verifier executions by tier and result",
        ["tier", "result"],
    ),
    "touchstone_ivp_tier_runs_total",
)
CACHE = _metric(
    lambda: Counter("touchstone_ivp_cache_total", "Fast-tier cache hits/misses", ["result"]),
    "touchstone_ivp_cache_total",
)
DEGRADATIONS = _metric(
    lambda: Counter(
        "touchstone_ivp_degradations_total",
        "Fail-open/closed fallbacks and backpressure rejections",
        ["reason", "fail_mode"],
    ),
    "touchstone_ivp_degradations_total",
)


def record_decision(action: str, mode: str, latency_s: float) -> None:
    DECISIONS.labels(action=action, mode=mode).inc()
    DECISION_LATENCY.labels(action=action, mode=mode).observe(latency_s)


def record_tier(tier: str, result: str) -> None:
    TIER_RUNS.labels(tier=tier, result=result).inc()


def record_cache(hit: bool) -> None:
    CACHE.labels(result="hit" if hit else "miss").inc()


def record_degradation(reason: str, fail_mode: str) -> None:
    DEGRADATIONS.labels(reason=reason, fail_mode=fail_mode).inc()
