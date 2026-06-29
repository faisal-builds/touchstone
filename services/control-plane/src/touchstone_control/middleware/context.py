"""Request-context middleware.

Assigns every request a stable ``X-Request-ID`` (honoring an inbound one for
trace continuity), binds it into the structlog contextvars so every log line in
the request is correlated, and emits a single structured access log with
latency. Prometheus request metrics are recorded here too.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import cast

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger("access")


def _metric[T](factory: Callable[[], T], name: str) -> T:
    """Register a metric, reusing an existing collector if already registered.

    Each Touchstone service runs in its own process in production, but two
    services can be imported into one process (e.g. the cross-service auth
    federation test), which would otherwise raise a duplicate-timeseries error.
    """
    try:
        return factory()
    except ValueError:
        from prometheus_client import REGISTRY
        return cast(T, REGISTRY._names_to_collectors[name])


REQUEST_COUNT = _metric(
    lambda: Counter(
        "touchstone_http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    ),
    "touchstone_http_requests_total",
)
REQUEST_LATENCY = _metric(
    lambda: Histogram(
        "touchstone_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    ),
    "touchstone_http_request_duration_seconds",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Route template (e.g. /v1/workspaces/{workspace_id}) for low-cardinality
        # metrics labels — never the raw path with IDs.
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            REQUEST_COUNT.labels(request.method, path_label, "500").inc()
            log.exception(
                "request.error", method=request.method, path=request.url.path
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(request.method, path_label).observe(elapsed)
        REQUEST_COUNT.labels(request.method, path_label, str(response.status_code)).inc()
        response.headers["X-Request-ID"] = request_id

        principal = getattr(request.state, "principal", None)
        log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed * 1000, 2),
            org_id=getattr(principal, "org_id", None),
            subject=getattr(principal, "subject", None),
        )
        return response
