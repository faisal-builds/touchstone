"""Auth + bootstrap integration tests (real app + real Postgres).

Covers the full self-serve path: signup mints a JWT, the JWT authenticates
subsequent calls, login round-trips, duplicates are rejected cleanly without
leaving partial state, and a JWT-authenticated user can create an API key.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from touchstone_control.app import create_app
from touchstone_control.core.config import Environment, Settings

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


@pytest.fixture
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
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def _signup_body():
    sfx = uuid.uuid4().hex[:10]
    return {
        "email": f"founder-{sfx}@example.com",
        "password": "correct horse battery staple",
        "full_name": "Ada Founder",
        "org_name": f"Acme {sfx}",
        "org_slug": f"acme-{sfx}",
    }


@pytest.mark.asyncio
async def test_signup_returns_jwt_and_creates_tenant(client):
    body = _signup_body()
    r = await client.post("/v1/auth/signup", json=body)
    assert r.status_code == 201, r.text
    tok = r.json()
    assert tok["token_type"] == "Bearer"
    assert tok["access_token"]
    assert tok["org_slug"] == body["org_slug"]

    # The freshly minted JWT must authenticate a protected call.
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    r2 = await client.get("/v1/workspaces", headers=auth)
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_email(client):
    body = _signup_body()
    assert (await client.post("/v1/auth/signup", json=body)).status_code == 201
    # Same email, different org slug -> 409 on email.
    dup = {**body, "org_slug": body["org_slug"] + "-2"}
    r = await client.post("/v1/auth/signup", json=dup)
    assert r.status_code == 409
    assert r.json()["type"].endswith("/conflict")


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_org_slug(client):
    body = _signup_body()
    assert (await client.post("/v1/auth/signup", json=body)).status_code == 201
    dup = {**body, "email": "other-" + body["email"]}
    r = await client.post("/v1/auth/signup", json=dup)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_email_leaves_no_partial_org(client, settings):
    """A rejected duplicate signup must not have created a second org."""
    body = _signup_body()
    await client.post("/v1/auth/signup", json=body)
    dup_slug = body["org_slug"] + "-orphan"
    await client.post("/v1/auth/signup", json={**body, "org_slug": dup_slug})
    engine = create_async_engine(str(settings.database_url))
    async with engine.connect() as c:
        n = (
            await c.execute(
                text("SELECT count(*) FROM organizations WHERE slug=:s"), {"s": dup_slug}
            )
        ).scalar()
    await engine.dispose()
    assert n == 0  # the orphan org was rolled back


@pytest.mark.asyncio
async def test_login_roundtrip(client):
    body = _signup_body()
    await client.post("/v1/auth/signup", json=body)
    r = await client.post(
        "/v1/auth/login", json={"email": body["email"], "password": body["password"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["org_slug"] == body["org_slug"]


@pytest.mark.asyncio
async def test_login_wrong_password_is_401(client):
    body = _signup_body()
    await client.post("/v1/auth/signup", json=body)
    r = await client.post(
        "/v1/auth/login", json={"email": body["email"], "password": "wrong"}
    )
    assert r.status_code == 401
    assert "Invalid email or password" in r.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_email_is_401(client):
    r = await client.post(
        "/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever12"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_user_can_create_api_key(client):
    body = _signup_body()
    tok = (await client.post("/v1/auth/signup", json=body)).json()
    auth = {"Authorization": f"Bearer {tok['access_token']}"}
    r = await client.post(
        "/v1/api-keys", json={"name": "ci-key", "role": "member"}, headers=auth
    )
    assert r.status_code == 201, r.text
    created = r.json()
    # The plaintext secret is returned exactly once and is a tsk_ key.
    assert created["secret"].startswith("tsk_")
    assert "key_id" in created

    # And that API key itself can then authenticate.
    key_auth = {"Authorization": f"Bearer {created['secret']}"}
    r2 = await client.get("/v1/workspaces", headers=key_auth)
    assert r2.status_code == 200
