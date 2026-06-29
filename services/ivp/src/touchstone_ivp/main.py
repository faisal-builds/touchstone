"""IVP application factory.

Builds the inline plane (policy engine, tiered executor, decision engine,
resilience primitives, event emitter) and exposes the gateway. Datastores are not
required to start: policies live in an epoch-versioned cache (production wires its
loader to the control-plane) and the broker is a NullPublisher in CI.
"""

from __future__ import annotations

import contextlib

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse, Response
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

    runner = SandboxRunner(SandboxLimits(
        cpu_seconds=settings.fast_cpu_seconds,
        memory_mb=settings.fast_memory_mb,
        wall_timeout_s=settings.fast_wall_timeout_s,
    ))
    warm_pool = None
    if settings.warm_pool_enabled:
        from touchstone_verify.sandbox.pool import WarmSandboxPool
        warm_pool = WarmSandboxPool(
            SandboxLimits(
                cpu_seconds=settings.fast_cpu_seconds,
                memory_mb=settings.fast_memory_mb,
                wall_timeout_s=settings.fast_wall_timeout_s,
            ),
            min_size=settings.warm_pool_min_size,
            max_size=settings.warm_pool_max_size,
            isolate_network=settings.warm_pool_isolate_network,
        )
        runner = warm_pool  # drop-in: same run(code, content) -> SandboxResult
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
