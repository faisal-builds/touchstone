"""Application factory.

Builds and wires the FastAPI app: settings -> runtime singletons (DB, security,
events, redis) -> middleware stack -> routers -> error handlers. Using a factory
(rather than a module-level app) makes the service trivially testable: tests
call `create_app(test_settings)` against ephemeral infra.

Middleware order (outermost first) is deliberate:
    RateLimit -> RequestContext -> CORS -> [routes]
so that rate-limited requests still get a request id and access log, and CORS
preflights are cheap.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from ._version import __version__
from .api.v1 import deps
from .api.v1.routers import (
    api_keys,
    audit,
    auth,
    health,
    internal_auth,
    projects,
    verifications,
    verifiers,
    workspaces,
)
from .core.config import Environment, Settings, get_settings
from .core.errors import (
    TouchstoneError,
    touchstone_error_handler,
    unhandled_error_handler,
)
from .core.security import SecurityService
from .db.audit_read import AuditReader
from .db.base import Database
from .middleware.context import RequestContextMiddleware
from .middleware.ratelimit import RateLimitMiddleware
from .middleware.security import SecurityHeadersMiddleware
from .observability.events import EventProducer
from .observability.logging import configure_logging, configure_tracing

log = structlog.get_logger(__name__)


def _validate_production_secrets(settings: Settings) -> None:
    if settings.is_production:
        if settings.jwt_secret.get_secret_value() == "dev-only-insecure-change-me":
            raise RuntimeError("Refusing to boot in production with the default JWT secret.")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    _validate_production_secrets(settings)

    database = Database(settings)
    audit_reader = AuditReader.from_settings(settings)
    security = SecurityService(settings)
    redis = Redis.from_url(str(settings.redis_url), decode_responses=True)
    events = EventProducer(
        settings.redpanda_brokers,
        enabled=settings.environment != Environment.CI,
    )
    deps.bind_runtime(database, security)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.db = database
        app.state.audit_reader = audit_reader
        app.state.redis = redis
        app.state.events = events
        await events.start()
        log.info("service.startup", service=settings.service_name, version=__version__)
        yield
        await events.stop()
        await redis.aclose()
        await database.dispose()
        await audit_reader.dispose()
        log.info("service.shutdown")

    app = FastAPI(
        title=f"{settings.product_name} Control Plane",
        version=__version__,
        description="Tenancy, identity, verifier registry, and verification "
        "orchestration for the AI Verification Layer.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # Bind runtime state at construction time so it is available even when the
    # ASGI lifespan is not run (e.g. httpx ASGITransport in tests). The lifespan
    # is still responsible for STARTING/STOPPING the event producer and for
    # disposing pooled resources on shutdown.
    app.state.settings = settings
    app.state.db = database
    app.state.audit_reader = audit_reader
    app.state.redis = redis
    app.state.events = events

    # --- Middleware (added last = outermost) ---------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        redis=redis,
        rate=settings.rate_limit_per_minute,
        burst=settings.rate_limit_burst,
    )
    # Outermost: hardening headers apply to every response, including errors and
    # rate-limited (429) responses.
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.is_production,
    )

    # --- Error handlers ------------------------------------------------------
    # Starlette types the handler's exc param as the base Exception; our handler
    # narrows it to TouchstoneError, which is sound at runtime (it's only invoked
    # for that type) but not expressible to the type checker — hence the cast.
    app.add_exception_handler(TouchstoneError, cast("Any", touchstone_error_handler))
    app.add_exception_handler(Exception, unhandled_error_handler)

    # --- Routers -------------------------------------------------------------
    app.include_router(health.router)
    v1 = "/v1"
    app.include_router(auth.router, prefix=v1)
    app.include_router(workspaces.router, prefix=v1)
    app.include_router(projects.router, prefix=v1)
    app.include_router(api_keys.router, prefix=v1)
    app.include_router(verifiers.router, prefix=v1)
    app.include_router(verifications.router, prefix=v1)
    app.include_router(audit.router, prefix=v1)
    app.include_router(internal_auth.router, prefix=v1)

    # --- Metrics endpoint (scraped by Prometheus) ----------------------------
    app.mount("/metrics", make_asgi_app())

    configure_tracing(app, settings)
    return app
