"""Security response headers for the RHD API (parity with the control-plane)."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/metrics")
_STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
}
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = True, hsts_max_age: int = 63072000) -> None:
        super().__init__(app)
        self._hsts = hsts
        self._hsts_value = f"max-age={hsts_max_age}; includeSubDomains; preload"

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for key, value in _STATIC_HEADERS.items():
            response.headers.setdefault(key, value)
        if self._hsts:
            response.headers.setdefault("Strict-Transport-Security", self._hsts_value)
        if not request.url.path.startswith(_DOCS_PREFIXES):
            response.headers.setdefault("Content-Security-Policy", _API_CSP)
        return response
