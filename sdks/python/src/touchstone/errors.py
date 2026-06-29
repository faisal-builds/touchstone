"""Typed exceptions for the Touchstone SDK.

The API returns ``application/problem+json`` (RFC 7807). The client parses that
body and raises the matching exception so callers can ``except NotFoundError``
rather than inspecting status codes. Every exception carries the problem
``detail`` and the originating ``status``/``type``.
"""

from __future__ import annotations


class TouchstoneError(Exception):
    """Base for all SDK errors."""

    def __init__(self, detail: str, *, status: int | None = None,
                 type_uri: str | None = None, body: dict | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.type_uri = type_uri
        self.body = body or {}


class AuthenticationError(TouchstoneError):
    """401 — missing/invalid credentials."""


class PermissionDeniedError(TouchstoneError):
    """403 — authenticated but not allowed."""


class NotFoundError(TouchstoneError):
    """404 — resource does not exist."""


class ConflictError(TouchstoneError):
    """409 — duplicate/conflicting resource (e.g. email or slug taken)."""


class ValidationError(TouchstoneError):
    """422 — request failed validation."""


class RateLimitError(TouchstoneError):
    """429 — too many requests."""

    def __init__(self, detail: str, *, retry_after: int | None = None, **kw) -> None:
        super().__init__(detail, **kw)
        self.retry_after = retry_after


class APIError(TouchstoneError):
    """5xx or any otherwise-unmapped status."""


_STATUS_MAP: dict[int, type[TouchstoneError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def error_for_status(status: int, body: dict, retry_after: int | None = None) -> TouchstoneError:
    detail = body.get("detail") or body.get("title") or f"HTTP {status}"
    type_uri = body.get("type")
    cls = _STATUS_MAP.get(status, APIError)
    if cls is RateLimitError:
        return RateLimitError(detail, retry_after=retry_after, status=status,
                              type_uri=type_uri, body=body)
    return cls(detail, status=status, type_uri=type_uri, body=body)
