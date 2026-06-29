"""Distributed rate limiting (ADR-007).

A token-bucket implemented atomically in Redis via a Lua script so limits hold
across all control-plane replicas. Keyed by principal subject when authenticated,
otherwise by client IP. Exceeding the limit returns RFC-7807 429 with
``Retry-After`` and ``X-RateLimit-*`` headers.
"""

from __future__ import annotations

import time

from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

# Atomic token-bucket refill+consume. Returns {allowed, remaining, reset_after}.
_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])      -- tokens per window
local burst = tonumber(ARGV[2])     -- max bucket size
local now = tonumber(ARGV[3])       -- epoch seconds
local window = tonumber(ARGV[4])    -- window seconds
local refill = rate / window

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = burst; ts = now end

local delta = math.max(0, now - ts)
tokens = math.min(burst, tokens + delta * refill)

local allowed = 0
if tokens >= 1 then allowed = 1; tokens = tokens - 1 end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(window * 2))
local reset_after = 0
if allowed == 0 then reset_after = math.ceil((1 - tokens) / refill) end
return {allowed, math.floor(tokens), reset_after}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, redis: Redis, *, rate: int, burst: int, window: int = 60
    ) -> None:
        super().__init__(app)
        self._redis = redis
        self._rate = rate
        self._burst = burst
        self._window = window
        self._sha: str | None = None

    async def _script(self) -> str:
        if self._sha is None:
            self._sha = await self._redis.script_load(_LUA)
        return self._sha

    def _identity(self, request: Request) -> str:
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            return f"rl:{principal.subject}"
        client = request.client.host if request.client else "unknown"
        return f"rl:ip:{client}"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip health probes — they must never be rate limited.
        if request.url.path in ("/healthz", "/readyz", "/metrics"):
            return await call_next(request)

        now = int(time.time())
        try:
            sha = await self._script()
            allowed, remaining, reset_after = await self._redis.evalsha(
                sha, 1, self._identity(request),
                self._rate, self._burst, now, self._window,
            )
        except Exception:
            # Fail-open on ANY Redis problem (outage, connection refused, script
            # load failure): availability is prioritized over strict limiting.
            return await call_next(request)

        if not allowed:
            return JSONResponse(
                status_code=429,
                media_type="application/problem+json",
                content={
                    "type": "https://errors.touchstone.ai/rate_limited",
                    "title": "Rate Limit Exceeded",
                    "status": 429,
                    "detail": "Too many requests.",
                    "instance": request.url.path,
                },
                headers={
                    "Retry-After": str(reset_after),
                    "X-RateLimit-Limit": str(self._rate),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._rate)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
