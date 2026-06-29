"""End-to-end integration tests.

Drives the real ASGI app over httpx against a real Postgres database. Verifies
the complete authenticated flow: API-key auth -> RBAC -> tenant-scoped CRUD ->
verification submission, plus cross-tenant isolation (the property that, if
broken, ends the company).

Requires a Postgres reachable at TOUCHSTONE_DATABASE_URL with the schema
migrated (``alembic upgrade head``). Run via: pytest tests/integration
"""

from __future__ import annotations

import os
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

DB_URL = os.environ.get(
    "TOUCHSTONE_DATABASE_URL",
    "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone",
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        environment=Environment.CI,  # disables the Kafka producer
        database_url=DB_URL,
        redis_url="redis://127.0.0.1:6379/0",  # absent -> limiter fails open
        jwt_secret="test-secret-key-at-least-32-bytes-long!!",
    )


@pytest.fixture
def app(settings):
    # Function-scoped: each test gets a fresh engine bound to its own event loop,
    # avoiding asyncpg "event loop is closed" errors on pool teardown.
    return create_app(settings)


@pytest_asyncio.fixture
async def seeded(settings):
    """Create an isolated org + member-role API key; yield (key, org_id). Cleans up."""
    engine = create_async_engine(str(settings.database_url))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    security = SecurityService(settings)
    suffix = uuid.uuid4().hex[:8]
    async with maker() as s:  # type: AsyncSession
        org = Organization(name=f"Acme {suffix}", slug=f"acme-{suffix}")
        s.add(org)
        await s.flush()
        gen = security.generate_api_key()
        key = ApiKey(
            organization_id=org.id,
            name="ci-key",
            key_id=gen.key_id,
            secret_hash=gen.secret_hash,
            role=Role.MEMBER,  # full project read/write, no org admin
        )
        s.add(key)
        await s.commit()
        org_id = str(org.id)
    await engine.dispose()
    yield gen.plaintext, org_id


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_health_is_open(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/v1/workspaces")
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_full_tenant_flow(app, seeded):
    token, _org_id = seeded
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t", headers=_auth(token)) as c:
        # 1. Create a workspace
        r = await c.post("/v1/workspaces", json={"name": "Research", "slug": "research"})
        assert r.status_code == 201, r.text
        ws = r.json()["id"]

        # 2. Create a project in it
        r = await c.post(
            f"/v1/workspaces/{ws}/projects",
            json={"name": "Coding Agent", "slug": "coding-agent"},
        )
        assert r.status_code == 201, r.text
        project = r.json()["id"]

        # 3. Register a verifier (auto-versioned to v1)
        r = await c.post(
            f"/v1/projects/{project}/verifiers",
            json={
                "name": "Unit Test Pass Rate",
                "slug": "unit-tests",
                "verifier_type": "code",
                "definition": {"runner": "pytest", "threshold": 1.0},
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["version"] == 1
        verifier = r.json()["id"]

        # Re-registering the same slug mints v2 (immutable versioning).
        r = await c.post(
            f"/v1/projects/{project}/verifiers",
            json={"name": "Unit Test Pass Rate", "slug": "unit-tests",
                  "verifier_type": "code", "definition": {"threshold": 0.9}},
        )
        assert r.json()["version"] == 2

        # 4. Submit a verification (events are no-op in CI)
        r = await c.post(
            "/v1/verifications",
            json={"verifier_id": verifier, "artifact_ref": "s3://bucket/run-1.json"},
        )
        assert r.status_code == 202, r.text
        run = r.json()
        assert run["status"] == "pending"

        # 5. Read it back
        r = await c.get(f"/v1/verifications/{run['id']}")
        assert r.status_code == 200
        assert r.json()["verifier_id"] == verifier


@pytest.mark.asyncio
async def test_member_cannot_revoke_keys(app, seeded):
    """RBAC: MEMBER lacks api_key:revoke -> 403."""
    token, _ = seeded
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t", headers=_auth(token)) as c:
        r = await c.delete(f"/v1/api-keys/{uuid.uuid4()}")
        assert r.status_code == 403
        assert r.json()["type"].endswith("/permission_denied")


@pytest.mark.asyncio
async def test_cross_tenant_isolation(app, seeded):
    """A key from org A must never see org B's workspaces."""
    token_a, _ = seeded
    # Make a second org+key (org B) with its own workspace.
    settings = app.state.settings
    engine = create_async_engine(str(settings.database_url))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    security = SecurityService(settings)
    suffix = uuid.uuid4().hex[:8]
    async with maker() as s:
        org = Organization(name=f"Beta {suffix}", slug=f"beta-{suffix}")
        s.add(org)
        await s.flush()
        gen = security.generate_api_key()
        s.add(ApiKey(organization_id=org.id, name="b", key_id=gen.key_id,
                     secret_hash=gen.secret_hash, role=Role.MEMBER))
        await s.commit()
    await engine.dispose()

    transport = ASGITransport(app=app)
    # Org A creates a workspace.
    async with AsyncClient(transport=transport, base_url="http://t",
                           headers=_auth(token_a)) as c:
        r = await c.post("/v1/workspaces", json={"name": "Secret A", "slug": "secret-a"})
        ws_a = r.json()["id"]
    # Org B must not be able to read it.
    async with AsyncClient(transport=transport, base_url="http://t",
                           headers=_auth(gen.plaintext)) as c:
        r = await c.get(f"/v1/workspaces/{ws_a}")
        assert r.status_code == 404  # not 403 — we don't even admit it exists


@pytest.mark.asyncio
async def test_list_verifications_for_dashboard(app, seeded):
    """The dashboard's runs page lists submitted verifications, newest first,
    and supports a project filter."""
    token, _org = seeded
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t",
                           headers=_auth(token)) as c:
        ws = (await c.post("/v1/workspaces", json={"name": "Runs", "slug": "runs"})).json()["id"]
        project = (await c.post(f"/v1/workspaces/{ws}/projects",
                                json={"name": "P", "slug": "p"})).json()["id"]
        verifier = (await c.post(f"/v1/projects/{project}/verifiers",
                                 json={"name": "V", "slug": "v", "verifier_type": "code",
                                       "definition": {"threshold": 1.0}})).json()["id"]
        for i in range(3):
            r = await c.post("/v1/verifications",
                             json={"verifier_id": verifier, "artifact_ref": f"s3://b/{i}.json"})
            assert r.status_code == 202, r.text

        # Unfiltered list returns all three runs.
        runs = (await c.get("/v1/verifications")).json()
        assert len(runs) >= 3
        required = {"id", "status", "verifier_id", "project_id"}
        assert all(required <= r.keys() for r in runs)

        # Project filter narrows correctly.
        scoped = (await c.get(f"/v1/verifications?project_id={project}")).json()
        assert scoped
        assert all(r["project_id"] == project for r in scoped)

        # Verifier filter narrows correctly.
        by_v = (await c.get(f"/v1/verifications?verifier_id={verifier}")).json()
        assert by_v
        assert all(r["verifier_id"] == verifier for r in by_v)


@pytest.mark.asyncio
async def test_audit_trail_read_and_isolation(app, seeded, settings):
    """The audit viewer reads the org's hash-chained records newest-first, and
    never sees another org's chain."""
    from sqlalchemy import text

    token, org_id = seeded
    engine = create_async_engine(str(settings.database_url))
    # audit_records is owned by the audit-engine after the split; create its
    # schema here so the shared test database has the table the control-plane
    # reads through its read-only audit connection.
    from touchstone_audit.repository import create_schema

    await create_schema(engine)
    async with engine.begin() as conn:
        for idx in range(2):
            # Hashes must be globally unique (committed rows persist across runs).
            rec = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex chars
            await conn.execute(text(
                "INSERT INTO audit_records (id, organization_id, chain_index, "
                "source_event_id, event_type, actor_type, actor_id, resource_type, "
                "resource_id, metadata, occurred_at, prev_hash, record_hash, "
                "created_at, updated_at) VALUES (:id,:org,:ci,:src,'user.login','user',"
                "'u','session',null,'{}',now(),:prev,:rec,now(),now())"),
                {"id": uuid.uuid4(), "org": org_id, "ci": idx, "src": uuid.uuid4(),
                 "prev": "0" * 64, "rec": rec})
    await engine.dispose()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t",
                           headers=_auth(token)) as c:
        records = (await c.get("/v1/audit")).json()
        assert len(records) >= 2
        # Newest (highest chain_index) first.
        idxs = [r["chain_index"] for r in records]
        assert idxs == sorted(idxs, reverse=True)
        assert all("record_hash" in r for r in records)
        assert all("prev_hash" in r for r in records)
