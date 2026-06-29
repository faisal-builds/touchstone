"""Internal auth introspection endpoint tests.

The reward-hacking-detector validates API keys through this endpoint instead of
reading the control-plane database directly (auth federation). These cover the
happy path, rejection of invalid keys (active: false, not 401), and the
service-token requirement that keeps the endpoint internal.
"""

from __future__ import annotations

import secrets
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from touchstone_control.app import create_app
from touchstone_control.core.config import Environment, Settings
from touchstone_control.core.security import SecurityService
from touchstone_control.db.models import ApiKey, Organization
from touchstone_control.domain.rbac import Role

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        environment=Environment.CI,
        database_url=DB_URL,
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret="test-secret-key-at-least-32-bytes-long!!",
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest_asyncio.fixture
async def seeded(settings):
    engine = create_async_engine(str(settings.database_url))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    security = SecurityService(settings)
    suffix = uuid.uuid4().hex[:8]
    async with maker() as s:
        org = Organization(name=f"Acme {suffix}", slug=f"acme-{suffix}")
        s.add(org)
        await s.flush()
        gen = security.generate_api_key()
        s.add(ApiKey(
            organization_id=org.id, name="ci-key", key_id=gen.key_id,
            secret_hash=gen.secret_hash, role=Role.MEMBER,
        ))
        await s.commit()
        org_id = str(org.id)
    await engine.dispose()
    yield gen.plaintext, org_id


def _service_headers(settings) -> dict:
    token = SecurityService(settings).issue_service_token(service="reward-hacking-detector")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_introspect_valid_key(app, seeded, settings):
    key, org_id = seeded
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/v1/internal/auth/introspect", json={"api_key": key},
                         headers=_service_headers(settings))
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["organization_id"] == org_id
    assert body["key_id"]
    assert body["api_key_id"]


@pytest.mark.asyncio
async def test_introspect_invalid_key_is_inactive(app, settings):
    bogus = f"tsk_{secrets.token_hex(8)}_{secrets.token_urlsafe(24)}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/v1/internal/auth/introspect", json={"api_key": bogus},
                         headers=_service_headers(settings))
    # Invalid key is reported inactive, not as an auth error (no oracle).
    assert r.status_code == 200
    assert r.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_requires_service_token(app, seeded):
    key, _ = seeded
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        # No service token at all.
        r1 = await c.post("/v1/internal/auth/introspect", json={"api_key": key})
        # A non-service (e.g. someone passing the API key itself) is rejected.
        r2 = await c.post("/v1/internal/auth/introspect", json={"api_key": key},
                          headers={"Authorization": f"Bearer {key}"})
    assert r1.status_code == 401
    assert r2.status_code == 401
