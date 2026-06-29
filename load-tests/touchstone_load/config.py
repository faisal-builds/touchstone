"""Profiles, thresholds, and runtime settings for the Touchstone load suite.

This module is the single source of truth for *how hard* and *against what* the
load test runs. The run scripts read the active profile here to set Locust's
``-u/-r/-t`` flags, and the locustfile reads the same profile to enforce
pass/fail thresholds — so the two never drift.

Everything is overridable by environment variable, so the same suite runs in CI
(smoke), locally, and against staging/AWS without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Thresholds:
    """Pass/fail gates evaluated when the run stops.

    A threshold of ``None`` means "do not enforce" (useful where a worker is not
    present, e.g. CI/local runs that cannot complete a verification end-to-end).
    """

    max_p95_ms: float | None
    max_p99_ms: float | None
    max_error_rate: float | None        # fraction 0..1 across all requests
    max_timeout_rate: float | None      # fraction of verification polls that timed out
    max_verification_completion_ms: float | None  # submit -> completed wall time


@dataclass(frozen=True)
class Profile:
    name: str
    users: int
    spawn_rate: float
    run_time: str                       # Locust duration, e.g. "30s", "5m"
    # Whether a verification worker is expected to be draining the queue. False
    # for CI/local (no broker/worker) — the hot-path user still measures submit
    # and poll latency, but does not fail the run for non-completion.
    expect_completion: bool
    poll_timeout_s: float               # max wait for a verification to complete
    poll_interval_s: float
    thresholds: Thresholds


# --- Built-in profiles ------------------------------------------------------
# Latency gates are deliberately generous: this suite is a regression tripwire
# and a pre-live baseline, not a micro-benchmark. Tune per environment via env.

PROFILES: dict[str, Profile] = {
    # CI tripwire: tiny, fast, no worker required. Catches gross regressions and
    # broken endpoints without making CI slow or flaky.
    "smoke": Profile(
        name="smoke", users=3, spawn_rate=3, run_time="20s",
        expect_completion=False, poll_timeout_s=5.0, poll_interval_s=0.5,
        thresholds=Thresholds(
            max_p95_ms=1500, max_p99_ms=3000, max_error_rate=0.02,
            max_timeout_rate=None, max_verification_completion_ms=None,
        ),
    ),
    # Local developer run against a single-node stack.
    "local": Profile(
        name="local", users=10, spawn_rate=2, run_time="1m",
        expect_completion=False, poll_timeout_s=15.0, poll_interval_s=0.5,
        thresholds=Thresholds(
            max_p95_ms=1000, max_p99_ms=2500, max_error_rate=0.01,
            max_timeout_rate=None, max_verification_completion_ms=None,
        ),
    ),
    # Steady-state load against a real staging cluster (broker + worker present).
    "staging": Profile(
        name="staging", users=50, spawn_rate=5, run_time="5m",
        expect_completion=True, poll_timeout_s=30.0, poll_interval_s=0.5,
        thresholds=Thresholds(
            max_p95_ms=800, max_p99_ms=2000, max_error_rate=0.01,
            max_timeout_rate=0.05, max_verification_completion_ms=15000,
        ),
    ),
    # Find the knee: high concurrency, looser latency gates, completion still
    # expected (a healthy system should keep draining the queue).
    "stress": Profile(
        name="stress", users=300, spawn_rate=20, run_time="10m",
        expect_completion=True, poll_timeout_s=60.0, poll_interval_s=1.0,
        thresholds=Thresholds(
            max_p95_ms=2500, max_p99_ms=6000, max_error_rate=0.05,
            max_timeout_rate=0.15, max_verification_completion_ms=45000,
        ),
    ),
}

DEFAULT_PROFILE = "smoke"


def _env_float(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def get_profile() -> Profile:
    """Resolve the active profile from ``TOUCHSTONE_LOAD_PROFILE`` and apply any
    per-threshold environment overrides (``TOUCHSTONE_LOAD_MAX_P95_MS`` etc.)."""
    name = os.environ.get("TOUCHSTONE_LOAD_PROFILE", DEFAULT_PROFILE).strip().lower()
    base = PROFILES.get(name)
    if base is None:
        raise SystemExit(
            f"Unknown profile {name!r}. Choose one of: {', '.join(PROFILES)}"
        )

    t = base.thresholds
    overridden = Thresholds(
        max_p95_ms=_env_float("TOUCHSTONE_LOAD_MAX_P95_MS", t.max_p95_ms),
        max_p99_ms=_env_float("TOUCHSTONE_LOAD_MAX_P99_MS", t.max_p99_ms),
        max_error_rate=_env_float("TOUCHSTONE_LOAD_MAX_ERROR_RATE", t.max_error_rate),
        max_timeout_rate=_env_float("TOUCHSTONE_LOAD_MAX_TIMEOUT_RATE", t.max_timeout_rate),
        max_verification_completion_ms=_env_float(
            "TOUCHSTONE_LOAD_MAX_COMPLETION_MS", t.max_verification_completion_ms
        ),
    )
    profile = replace(base, thresholds=overridden)

    # Allow scaling knobs to be overridden too (handy for ad-hoc runs).
    users = os.environ.get("TOUCHSTONE_LOAD_USERS")
    spawn = os.environ.get("TOUCHSTONE_LOAD_SPAWN_RATE")
    run_time = os.environ.get("TOUCHSTONE_LOAD_RUN_TIME")
    expect = os.environ.get("TOUCHSTONE_LOAD_EXPECT_COMPLETION")
    return replace(
        profile,
        users=int(users) if users else profile.users,
        spawn_rate=float(spawn) if spawn else profile.spawn_rate,
        run_time=run_time or profile.run_time,
        expect_completion=(
            expect.lower() in ("1", "true", "yes") if expect else profile.expect_completion
        ),
    )


@dataclass(frozen=True)
class TargetSettings:
    """Where to point the load, and what payloads to use."""

    control_plane_url: str
    rhd_url: str
    # Reference passed as the artifact under test. In staging/AWS this should be
    # an object that exists in the configured artifact store so the worker can
    # load it; locally it is simply persisted with the run.
    artifact_ref: str
    # Whether to drive the reward-hacking-detector scenarios (needs the RHD up).
    enable_rhd: bool


def get_targets() -> TargetSettings:
    return TargetSettings(
        control_plane_url=os.environ.get(
            "TOUCHSTONE_LOAD_HOST", "http://localhost:8000"
        ).rstrip("/"),
        rhd_url=os.environ.get("TOUCHSTONE_LOAD_RHD_URL", "http://localhost:8030").rstrip("/"),
        artifact_ref=os.environ.get("TOUCHSTONE_LOAD_ARTIFACT_REF", "load/sample.json"),
        enable_rhd=os.environ.get("TOUCHSTONE_LOAD_ENABLE_RHD", "false").lower()
        in ("1", "true", "yes"),
    )
