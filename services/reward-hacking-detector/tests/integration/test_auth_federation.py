"""End-to-end auth federation: the RHD introspector against the real control-plane.

Proves the cross-service path works without RHD touching the control-plane
database: a real API key is seeded in the control-plane, and RHD's
``HttpIntrospector`` validates it by calling the control-plane's introspection
endpoint (over an in-process ASGI transport) with a shared-secret service token.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from touchstone_control.app import create_app as create_cp_app
from touchstone_control.core.config import Environment as CPEnvironment
from touchstone_control.core.config import Settings as CPSettings
from touchstone_control.core.security import SecurityService
from touchstone_control.db.models import ApiKey, Organization
from touchstone_control.domain.rbac import Role

from touchstone_rhd.api.introspect import HttpIntrospector

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"
SHARED_SECRET = "shared-secret-at-least-32-bytes-long-for-hs256!!"


async def _seed_control_plane_key():
    settings = CPSettings(
        environment=CPEnvironment.CI, database_url=DB_URL,
        redis_url="redis://127.0.0.1:6379/0", jwt_secret=SHARED_SECRET,
    )
    security = SecurityService(settings)
    engine = create_async_engine(DB_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    sfx = uuid.uuid4().hex[:8]
    async with maker() as s:
        org = Organization(name=f"Acme {sfx}", slug=f"acme-{sfx}")
        s.add(org)
        await s.flush()
        gen = security.generate_api_key()
        s.add(ApiKey(
            organization_id=org.id, name="k", key_id=gen.key_id,
            secret_hash=gen.secret_hash, role=Role.MEMBER,
        ))
        await s.commit()
        org_id = org.id
    await engine.dispose()
    return create_cp_app(settings), gen.plaintext, org_id


@pytest.mark.asyncio
async def test_rhd_introspects_real_control_plane():
    cp_app, key, org_id = await _seed_control_plane_key()
    transport = httpx.ASGITransport(app=cp_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cp") as client:
        introspector = HttpIntrospector(
            base_url="http://cp", jwt_secret=SHARED_SECRET, jwt_algorithm="HS256",
            service_name="reward-hacking-detector", client=client,
        )
        principal = await introspector.introspect(key)
        assert principal is not None
        assert principal.organization_id == org_id

        # An unknown key is rejected (returns None, not an exception).
        assert await introspector.introspect("tsk_deadbeef_not-a-real-secret") is None


@pytest.mark.asyncio
async def test_introspector_caches_positive_result():
    cp_app, key, org_id = await _seed_control_plane_key()
    transport = httpx.ASGITransport(app=cp_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cp") as client:
        introspector = HttpIntrospector(
            base_url="http://cp", jwt_secret=SHARED_SECRET, jwt_algorithm="HS256",
            service_name="reward-hacking-detector", client=client, cache_ttl_seconds=60,
        )
        first = await introspector.introspect(key)
        # Close the transport; a cached hit must not require another round-trip.
        await client.aclose()
        second = await introspector.introspect(key)
    assert first is not None and second is not None
    assert second.organization_id == org_id
