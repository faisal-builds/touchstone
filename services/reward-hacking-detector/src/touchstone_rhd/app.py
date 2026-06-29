"""FastAPI application factory for the reward-hacking-detector API."""

from __future__ import annotations

import contextlib

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_verify.sandbox.base import build_sandbox

from . import _version
from .api.introspect import HttpIntrospector
from .config import Environment, Settings, get_settings
from .knowledge.repository import KnowledgeBase
from .middleware.metrics import RequestMetricsMiddleware
from .middleware.security import SecurityHeadersMiddleware
from .observability.logging import configure_logging, configure_tracing
from .orchestrator import Orchestrator
from .publisher import NullPublisher, Publisher
from .worker import EvaluationJobRunner


def create_app(
    settings: Settings | None = None,
    *,
    publisher: Publisher | None = None,
    introspector: object | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    introspector = introspector or HttpIntrospector.from_settings(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
        app.state.engine = engine
        app.state.kb = KnowledgeBase(engine)
        sandbox = build_sandbox(
            settings.sandbox_backend,
            image=settings.sandbox_image,
            allow_fallback=settings.sandbox_allow_fallback,
        )
        app.state.runner = EvaluationJobRunner(
            kb=app.state.kb,
            orchestrator=Orchestrator(sandbox=sandbox),
            publisher=publisher or NullPublisher(),
            max_retries=settings.max_retries,
            retry_backoff_s=settings.retry_backoff_s,
        )
        try:
            yield
        finally:
            await engine.dispose()
            aclose = getattr(introspector, "aclose", None)
            if aclose is not None:
                await aclose()

    app = FastAPI(
        title="Touchstone Reward-Hacking Detector",
        version=_version.__version__,
        summary="Evaluate how robust an AI verifier is against manipulation.",
        lifespan=lifespan,
    )
    # Bound at construction so it is present even when the ASGI lifespan is not
    # run (e.g. tests using httpx ASGITransport that wire state directly).
    app.state.introspector = introspector

    from .api.routers import router as robustness_router

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.environment == Environment.PRODUCTION,
    )
    app.add_middleware(RequestMetricsMiddleware)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": settings.service_name})

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        # Readiness depends on the database being reachable.
        checks: dict[str, str] = {}
        try:
            engine = app.state.engine
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:  # noqa: BLE001
            checks["database"] = "unavailable"
        ready = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ready" if ready else "degraded",
             "service": settings.service_name,
             "version": _version.__version__, "checks": checks},
            status_code=200 if ready else 503,
        )

    app.include_router(robustness_router)
    app.mount("/metrics", make_asgi_app())
    configure_tracing(app, settings)
    return app
