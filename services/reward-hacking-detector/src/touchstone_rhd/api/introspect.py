"""API-key introspection client (auth federation).

Rather than reading the control-plane's ``api_keys`` table, the RHD validates a
presented ``tsk_`` key by calling the control-plane's internal introspection
endpoint. This keeps the control-plane the single owner of key material (no
Argon2 secret hashes are replicated here) and lets the RHD run on a fully
isolated database.

The call is authenticated with a short-lived service token signed with the shared
secret. Positive results are cached for a short TTL to avoid a network round-trip
and an Argon2 verification on every request; the TTL bounds revocation staleness.
"""

from __future__ import annotations

import datetime as _dt
import time
import uuid
from typing import Protocol

import httpx
import jwt

from ..config import Settings
from .auth import Principal


class Introspector(Protocol):
    async def introspect(self, api_key: str) -> Principal | None: ...


class HttpIntrospector:
    """Validates API keys against the control-plane introspection endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_secret: str,
        jwt_algorithm: str,
        service_name: str,
        cache_ttl_seconds: int = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = jwt_secret
        self._alg = jwt_algorithm
        self._service = service_name
        self._ttl = cache_ttl_seconds
        self._client = client
        self._owns_client = client is None
        self._cache: dict[str, tuple[float, Principal]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> HttpIntrospector:
        return cls(
            base_url=settings.control_plane_url,
            jwt_secret=settings.jwt_secret,
            jwt_algorithm=settings.jwt_algorithm,
            service_name=settings.service_name,
            cache_ttl_seconds=settings.auth_cache_ttl_seconds,
        )

    def _service_token(self) -> str:
        now = _dt.datetime.now(_dt.UTC)
        return jwt.encode(
            {
                "sub": self._service,
                "type": "service",
                "iat": now,
                "exp": now + _dt.timedelta(seconds=60),
                "jti": str(uuid.uuid4()),
            },
            self._secret,
            algorithm=self._alg,
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=5.0)
        return self._client

    async def introspect(self, api_key: str) -> Principal | None:
        cached = self._cache.get(api_key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

        client = self._get_client()
        try:
            resp = await client.post(
                "/v1/internal/auth/introspect",
                json={"api_key": api_key},
                headers={"Authorization": f"Bearer {self._service_token()}"},
            )
        except httpx.HTTPError:
            # Fail closed: if the control-plane is unreachable, deny.
            return None
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data.get("active"):
            return None
        principal = Principal(
            organization_id=uuid.UUID(str(data["organization_id"])),
            key_id=str(data.get("key_id") or ""),
        )
        # Cache positive results only; negatives are not cached so a freshly
        # created key is usable immediately.
        self._cache[api_key] = (time.monotonic() + self._ttl, principal)
        return principal

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
