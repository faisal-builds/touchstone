"""IVP configuration.

Tunables for the inline plane: the default latency budget, fail mode, backpressure
limits, and the addresses of the services it federates with. Every value is
environment-overridable (prefix ``TOUCHSTONE_IVP_``) so the same image runs in CI,
locally, and per-region in production.
"""

from __future__ import annotations

import enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, enum.Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class FailMode(str, enum.Enum):
    """What the plane does when it cannot reach a verdict in time/health.

    ``open`` favors availability (let traffic through); ``closed`` favors safety
    (block). The right choice is per-policy, but this is the plane-wide default.
    """

    OPEN = "open"
    CLOSED = "closed"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOUCHSTONE_IVP_", env_file=".env", extra="ignore"
    )

    service_name: str = "ivp"
    environment: Environment = Environment.LOCAL

    # Region identity for this plane replica (multi-region awareness).
    region_id: str = "local"
    region_locality: str = "local"
    # Global policy distribution: resolve policies via a region-local replica fed by
    # the global control-plane log (so a policy authored in any region resolves
    # here). Off by default (parity with the single-region in-memory store).
    distribution_enabled: bool = False

    # Shared JWT (same secret as the control-plane) for user tokens + minting the
    # short-lived service token used to call the introspection endpoint.
    jwt_secret: str = "change-me-in-prod-with-a-32-byte-minimum-secret"
    jwt_algorithm: str = "HS256"

    # Auth federation: validate tsk_ keys via the control-plane (the IVP, like the
    # RHD, reads no control-plane tables).
    control_plane_url: str = "http://localhost:8000"
    auth_cache_ttl_seconds: int = 30

    # Event bus (decisions -> audit, escalations -> verification-engine,
    # evasion -> RHD). Disabled in CI (NullPublisher) like the other services.
    redpanda_brokers: str = "localhost:19092"

    # --- Inline plane defaults (overridable per-policy) ---------------------
    # The wall-clock budget for a verify call; the fast tier must finish within it.
    default_latency_budget_ms: float = 150.0
    default_fail_mode: FailMode = FailMode.OPEN
    # Backpressure: max concurrent inline verifications in flight per replica.
    max_concurrent_inflight: int = 256
    # Circuit breaker: consecutive tier failures before the tier is shed.
    breaker_failure_threshold: int = 20
    breaker_reset_seconds: float = 5.0
    # Fast-tier result cache (content+verifier keyed) — dedup identical traffic.
    cache_max_entries: int = 50_000
    cache_ttl_seconds: float = 30.0

    # Sandbox tuning for the *inline* tier — much tighter than the batch engine.
    fast_cpu_seconds: int = 1
    fast_memory_mb: int = 128
    fast_wall_timeout_s: float = 0.5
    # Isolation backend for the inline tier. ``gvisor`` / ``firecracker`` are the
    # hardened production boundaries; ``subprocess`` is the INSECURE local-dev
    # baseline (no filesystem isolation) and is refused unless the explicit
    # TOUCHSTONE_ALLOW_INSECURE_SANDBOX opt-in is set. Default stays ``subprocess``
    # so a fresh deploy must make a conscious choice (hardened backend or opt-in)
    # rather than silently running untrusted code unisolated.
    sandbox_backend: str = "subprocess"
    sandbox_image: str = "touchstone/sandbox:latest"
    # Fail CLOSED: if the selected hardened backend's runtime is unavailable, refuse
    # to run rather than silently degrading to the insecure subprocess baseline.
    # (A degrade is only ever honored alongside the explicit insecure opt-in.)
    sandbox_allow_fallback: bool = False

    # Warm sandbox pool: keep pre-started single-use workers so the hot path skips
    # process spawn + interpreter startup. Off by default (parity with the plain
    # runner); enable in latency-sensitive deployments.
    warm_pool_enabled: bool = False
    warm_pool_min_size: int = 8
    warm_pool_max_size: int = 64
    warm_pool_isolate_network: bool = True


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
