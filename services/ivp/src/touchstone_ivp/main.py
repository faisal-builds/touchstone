"""IVP application factory.

Builds the inline plane (policy engine, tiered executor, decision engine,
resilience primitives, event emitter) and exposes the gateway. Datastores are not
required to start: policies live in an epoch-versioned cache (production wires its
loader to the control-plane) and the broker is a NullPublisher in CI.
"""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse, Response
from touchstone_verify.sandbox.base import IsolationBackend, Sandbox, build_sandbox
from touchstone_verify.sandbox.runner import SandboxLimits, SandboxRunner

from . import _version
from .config import Environment, Settings, get_settings
from .decision import DecisionEngine
from .events import InlineEventEmitter, NullPublisher, Publisher
from .execution import ResultCache
from .gateway import router as inline_router
from .introspect import HttpIntrospector
from .plane import InlinePlane
from .policy import PolicyEngine, PolicyStore, RobustnessCache
from .resilience import Bulkhead, CircuitBreaker

if TYPE_CHECKING:
    from touchstone_verify.sandbox.pool import WarmSandboxPool

_log = structlog.get_logger(__name__)

# Loud, explicit opt-in for the INSECURE subprocess sandbox. The subprocess /
# warm-pool backends give no filesystem isolation, so they must never run
# untrusted grader code outside local dev. This env var is intentionally NOT
# namespaced under TOUCHSTONE_IVP_ — it is a deliberate, conspicuous override a
# developer sets by hand, never something that rides along in a service config.
INSECURE_SANDBOX_ENV = "TOUCHSTONE_ALLOW_INSECURE_SANDBOX"
_TRUTHY = {"1", "true", "yes", "on"}


class InsecureSandboxError(RuntimeError):
    """Raised when IVP would run untrusted code without isolation but was not
    explicitly authorized to (fail closed)."""


def _insecure_sandbox_opt_in() -> bool:
    return os.environ.get(INSECURE_SANDBOX_ENV, "").strip().lower() in _TRUTHY


def build_inline_runner(settings: Settings) -> tuple[Sandbox, WarmSandboxPool | None]:
    """Select the inline-tier sandbox runner from configuration.

    Returns ``(runner, warm_pool)`` where ``warm_pool`` is non-None only when the
    pre-warmed pool is actually in use (so the caller can manage its lifecycle).

    Policy:

    * **Hardened backend** (``gvisor`` / ``firecracker``) — built via
      :func:`build_sandbox`, honoring IVP's tight ``fast_*`` limits. The warm pool
      is subprocess-native and is therefore *gated off* here. Fails **closed**: a
      missing runtime raises (``allow_fallback`` defaults False) and a silent
      downgrade to the subprocess baseline is permitted only when the insecure
      opt-in is set.
    * **Subprocess backend** — insecure (no filesystem isolation). Permitted only
      when :data:`INSECURE_SANDBOX_ENV` is explicitly set; otherwise refused. The
      warm pool may be used on this path.
    """

    limits = SandboxLimits(
        cpu_seconds=settings.fast_cpu_seconds,
        memory_mb=settings.fast_memory_mb,
        wall_timeout_s=settings.fast_wall_timeout_s,
    )
    backend = IsolationBackend(settings.sandbox_backend)

    if backend is IsolationBackend.SUBPROCESS:
        if not _insecure_sandbox_opt_in():
            raise InsecureSandboxError(
                "IVP is configured for the 'subprocess' sandbox, which provides no "
                "filesystem isolation and must never run untrusted grader code "
                "outside local dev. Select a hardened backend "
                "(TOUCHSTONE_IVP_SANDBOX_BACKEND=gvisor|firecracker), or — for "
                f"local dev ONLY — set {INSECURE_SANDBOX_ENV}=1 to explicitly "
                "accept insecure, unisolated execution."
            )
        _log.warning(
            "ivp.sandbox.insecure_enabled",
            backend="subprocess",
            warm_pool=settings.warm_pool_enabled,
            detail=(
                "INSECURE: untrusted grader code runs with NO filesystem isolation; "
                f"permitted only because {INSECURE_SANDBOX_ENV} is set. "
                "Never use in production."
            ),
        )
        if settings.warm_pool_enabled:
            from touchstone_verify.sandbox.pool import WarmSandboxPool

            pool = WarmSandboxPool(
                limits,
                min_size=settings.warm_pool_min_size,
                max_size=settings.warm_pool_max_size,
                isolate_network=settings.warm_pool_isolate_network,
            )
            return pool, pool
        return SandboxRunner(limits), None

    # Hardened backend. The warm pool is subprocess-native and MUST NOT front a
    # hardened runtime, so gate it off (loudly, if the operator had enabled it).
    if settings.warm_pool_enabled:
        _log.warning(
            "ivp.warm_pool.disabled_for_hardened_backend",
            backend=backend.value,
            detail="warm pool is subprocess-only; ignored under a hardened backend",
        )
    # Fail closed: a silent downgrade to the insecure subprocess baseline is only
    # ever allowed when the operator has explicitly opted into insecure execution.
    allow_fallback = settings.sandbox_allow_fallback and _insecure_sandbox_opt_in()
    sandbox = build_sandbox(
        backend,
        limits=limits,
        image=settings.sandbox_image,
        allow_fallback=allow_fallback,
    )
    return sandbox, None


def create_app(
    settings: Settings | None = None,
    *,
    introspector: object | None = None,
    publisher: Publisher | None = None,
    policy_engine: PolicyEngine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    introspector = introspector or HttpIntrospector.from_settings(settings)
    distribution = None
    if policy_engine is None:
        if settings.distribution_enabled:
            from .distribution import GlobalPolicyDistribution
            distribution = GlobalPolicyDistribution(settings.region_id)
            policy_engine = PolicyEngine(
                PolicyStore(loader=distribution.loader), RobustnessCache()
            )
        else:
            policy_engine = PolicyEngine(PolicyStore(), RobustnessCache())

    # Select the inline sandbox from configuration: a hardened backend via
    # build_sandbox (fail-closed), or the explicitly-opted-in insecure subprocess
    # baseline. The warm pool is returned only when it is actually in use.
    runner, warm_pool = build_inline_runner(settings)
    cache = ResultCache(
        max_entries=settings.cache_max_entries, ttl_s=settings.cache_ttl_seconds
    )
    bulkhead = Bulkhead(settings.max_concurrent_inflight)
    breaker = CircuitBreaker(
        failure_threshold=settings.breaker_failure_threshold,
        reset_seconds=settings.breaker_reset_seconds,
    )
    emitter = InlineEventEmitter(publisher or NullPublisher())
    from .enterprise import EnterpriseContext
    enterprise = EnterpriseContext(
        region_id=settings.region_id, locality=settings.region_locality
    )
    plane = InlinePlane(
        policy_engine=policy_engine, decision_engine=DecisionEngine(), emitter=emitter,
        bulkhead=bulkhead, breaker=breaker, runner=runner, cache=cache, settings=settings,
        enterprise=enterprise,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if warm_pool is not None:
            await warm_pool.start()
        try:
            yield
        finally:
            if warm_pool is not None:
                await warm_pool.aclose()
            aclose = getattr(introspector, "aclose", None)
            if aclose is not None:
                await aclose()

    app = FastAPI(
        title="Touchstone Inline Verification Plane",
        version=_version.__version__,
        summary="Allow / block / redact / escalate decisions on live AI traffic.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.introspector = introspector
    app.state.policy_engine = policy_engine
    app.state.plane = plane
    app.state.enterprise = enterprise
    app.state.distribution = distribution

    app.include_router(inline_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": settings.service_name})

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        # The plane has no hard datastore dependency to start; readiness reflects
        # that the bulkhead has capacity and the breaker is not wedged open.
        ready = bulkhead.inflight < settings.max_concurrent_inflight
        return JSONResponse(
            {"status": "ready" if ready else "saturated", "breaker": breaker.state},
            status_code=200 if ready else 503,
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/ops/status", tags=["ops"], summary="Enterprise operations status")
    async def ops_status() -> JSONResponse:
        # Region, SLO attainment/burn, resilience state, and warm-pool stats — the
        # data behind the enterprise operations dashboard.
        body = dict(enterprise.status())
        body["resilience"] = {
            "bulkhead_inflight": bulkhead.inflight,
            "bulkhead_limit": settings.max_concurrent_inflight,
            "breaker_state": breaker.state,
        }
        pool_stats = getattr(warm_pool, "stats", None)
        if pool_stats is not None:
            body["warm_pool"] = {
                "size": warm_pool.size, "idle": warm_pool.idle,
                "warm_hits": pool_stats.warm_hits, "cold_spills": pool_stats.cold_spills,
                "exhausted": pool_stats.exhausted,
            }
        return JSONResponse(body)

    return app


def app() -> FastAPI:  # uvicorn entry: touchstone_ivp.app:app (factory)
    settings = get_settings()
    if settings.environment == Environment.CI:
        return create_app(settings, publisher=NullPublisher())
    return create_app(settings)
