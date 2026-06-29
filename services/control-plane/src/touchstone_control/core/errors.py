"""Error taxonomy + handlers.

Every error the API returns is a machine-readable ``application/problem+json``
document (RFC 7807). This is a hard requirement for an enterprise platform:
customers integrate against stable error ``type`` URIs, not prose.
"""

from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse

ERROR_BASE = "https://errors.touchstone.ai"


class TouchstoneError(Exception):
    """Base class for all domain errors. Maps 1:1 to an HTTP problem document."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_type: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(self, detail: str | None = None, **extra: object) -> None:
        self.detail = detail or self.title
        self.extra = extra
        super().__init__(self.detail)

    def to_problem(self, instance: str) -> dict[str, object]:
        body: dict[str, object] = {
            "type": f"{ERROR_BASE}/{self.error_type}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
            "instance": instance,
        }
        body.update(self.extra)
        return body


class NotFoundError(TouchstoneError):
    status_code = status.HTTP_404_NOT_FOUND
    error_type = "not_found"
    title = "Resource Not Found"


class ConflictError(TouchstoneError):
    status_code = status.HTTP_409_CONFLICT
    error_type = "conflict"
    title = "Resource Conflict"


class AuthenticationError(TouchstoneError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_type = "unauthenticated"
    title = "Authentication Required"


class PermissionDeniedError(TouchstoneError):
    status_code = status.HTTP_403_FORBIDDEN
    error_type = "permission_denied"
    title = "Permission Denied"


class ValidationError(TouchstoneError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_type = "validation_error"
    title = "Validation Failed"


class RateLimitedError(TouchstoneError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_type = "rate_limited"
    title = "Rate Limit Exceeded"


async def touchstone_error_handler(request: Request, exc: TouchstoneError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_problem(instance=str(request.url.path)),
        media_type="application/problem+json",
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals. The real exception is logged with the request id.
    return JSONResponse(
        status_code=500,
        content={
            "type": f"{ERROR_BASE}/internal_error",
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": str(request.url.path),
        },
        media_type="application/problem+json",
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )
