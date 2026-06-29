"""Security response headers are applied to every response (ADR-012)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from touchstone_control.app import create_app
from touchstone_control.core.config import Environment, Settings

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


@pytest.fixture
def prod_app():
    # Production environment so HSTS is asserted, and a strong secret so the
    # production-secret guard permits boot.
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_url=DB_URL,
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret="prod-secret-key-at-least-32-bytes-long!!",
    )
    return create_app(settings)


@pytest_asyncio.fixture
async def client(prod_app):
    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.mark.asyncio
async def test_security_headers_present_on_api(client):
    r = await client.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert "max-age=" in r.headers["Strict-Transport-Security"]


@pytest.mark.asyncio
async def test_docs_paths_are_exempt_from_strict_csp(client):
    # The interactive docs load CDN assets; a default-src 'none' CSP would break
    # them, so they are exempted while still getting the other hardening headers.
    r = await client.get("/openapi.json")
    assert "Content-Security-Policy" not in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"
