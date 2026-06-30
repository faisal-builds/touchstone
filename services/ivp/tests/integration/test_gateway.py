"""End-to-end gateway tests: policy CRUD, inline verify, streaming early-exit.

Uses a fake introspector so no control-plane is required; the sandbox runs for
real, exercising the full hot path through HTTP.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from touchstone_verify.sandbox.runner import sandbox_supported

from touchstone_ivp.auth import Principal
from touchstone_ivp.config import Environment, Settings
from touchstone_ivp.events import NullPublisher
from touchstone_ivp.main import create_app

# The gateway hot path runs the real POSIX sandbox; skip — never fail — where
# fork/rlimits are unavailable (Windows). Exercised for real in CI on Linux.
pytestmark = pytest.mark.skipif(
    not sandbox_supported(),
    reason="POSIX process sandbox (fork/rlimits/unshare) unavailable on this platform",
)

ORG = uuid.uuid4()
SAFE_CODE = "def check(artifact):\n    return {'score': 0.0 if 'dangerous' in artifact else 1.0}"


class FakeIntrospector:
    async def introspect(self, api_key: str) -> Principal | None:
        return Principal(organization_id=ORG, key_id="test-key")

    async def aclose(self) -> None:
        return None


@pytest.fixture
def app():
    return create_app(
        Settings(environment=Environment.CI),
        introspector=FakeIntrospector(),
        publisher=NullPublisher(),
    )


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ivp") as c:
        yield c


AUTH = {"Authorization": "Bearer tsk_abc_def"}


async def _create_policy(client, **overrides):
    body = {
        "slug": "default",
        "project_id": str(uuid.uuid4()),
        "verifiers": [{
            "verifier_id": str(uuid.uuid4()),
            "tier": "auto",
            "definition": {"code": SAFE_CODE, "threshold": 1.0},
        }],
        "thresholds": {"block_at": 0.5},
    }
    body.update(overrides)
    resp = await client.post("/v1/inline/policies", json=body, headers=AUTH)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_requires_auth(client):
    resp = await client.post("/v1/inline/verify", json={"content": "x", "policy_slug": "p"})
    assert resp.status_code == 401


async def test_create_and_get_policy(client):
    created = await _create_policy(client)
    got = await client.get(f"/v1/inline/policies/{created['id']}", headers=AUTH)
    assert got.status_code == 200
    assert got.json()["slug"] == "default"


async def test_verify_allows_safe_content(client):
    await _create_policy(client)
    resp = await client.post(
        "/v1/inline/verify",
        json={"policy_slug": "default", "content": "this is safe"}, headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "allow"
    assert body["content_sha256"]


async def test_verify_blocks_dangerous_content(client):
    await _create_policy(client)
    resp = await client.post(
        "/v1/inline/verify",
        json={"policy_slug": "default", "content": "this is dangerous"}, headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "block"


async def test_verify_unknown_policy_404(client):
    resp = await client.post(
        "/v1/inline/verify",
        json={"policy_slug": "nope", "content": "x"}, headers=AUTH,
    )
    assert resp.status_code == 404


async def test_streaming_early_exits_on_block(client):
    await _create_policy(client)
    resp = await client.post(
        "/v1/inline/verify/stream",
        json={
            "policy_slug": "default",
            "chunks": ["this is ", "safe so far ", "but now dangerous", " and more"],
        },
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    verdicts = resp.json()
    # The 3rd chunk introduces "dangerous" -> block, and streaming stops there.
    assert verdicts[-1]["action"] == "block"
    assert verdicts[-1]["terminal"] is True
    assert len(verdicts) < 4


async def test_warm_pool_backed_plane_verifies():
    """With warm_pool_enabled the lifespan pre-warms the pool and the fast tier
    runs verifiers on warm workers — proven end-to-end through HTTP."""
    app = create_app(
        Settings(environment=Environment.CI, warm_pool_enabled=True,
                 warm_pool_min_size=2, warm_pool_max_size=8,
                 warm_pool_isolate_network=False, fast_wall_timeout_s=5.0),
        introspector=FakeIntrospector(), publisher=NullPublisher(),
    )
    async with app.router.lifespan_context(app):  # runs pool.start() / aclose()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://ivp") as c:
            await _create_policy(c)
            ok = await c.post("/v1/inline/verify",
                              json={"policy_slug": "default", "content": "this is safe"},
                              headers=AUTH)
            bad = await c.post("/v1/inline/verify",
                               json={"policy_slug": "default", "content": "this is dangerous"},
                               headers=AUTH)
    assert ok.status_code == 200 and ok.json()["action"] == "allow"
    assert bad.status_code == 200 and bad.json()["action"] == "block"
