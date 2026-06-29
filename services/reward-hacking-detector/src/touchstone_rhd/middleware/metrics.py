"""Prometheus HTTP request metrics for the RHD API (parity with control-plane).

Emits the same metric names as the control-plane so a single Grafana dashboard
panel, split by the Prometheus ``job`` label, covers every HTTP service.
"""

from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def _metric(factory, name):
    """Register a metric, reusing an existing collector if already registered.

    Each Touchstone service runs in its own process in production, but two
    services can be imported into one process (e.g. the cross-service auth
    federation test), which would otherwise raise a duplicate-timeseries error.
    """
    try:
        return factory()
    except ValueError:
        from prometheus_client import REGISTRY
        return REGISTRY._names_to_collectors[name]


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


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Low-cardinality route template, never the raw path with IDs.
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)
        start = time.perf_counter()
        response = await call_next(request)
        REQUEST_LATENCY.labels(request.method, path_label).observe(
            time.perf_counter() - start
        )
        REQUEST_COUNT.labels(request.method, path_label, response.status_code).inc()
        return response
