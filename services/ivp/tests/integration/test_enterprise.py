"""Enterprise integration: region stamping, SLO recording, chaos degradation, ops API."""

from __future__ import annotations

import uuid

import httpx
import pytest

from touchstone_ivp.auth import Principal
from touchstone_ivp.config import Environment, Settings
from touchstone_ivp.events import NullPublisher
from touchstone_ivp.main import create_app

ORG = uuid.uuid4()
GUARD = "def check(artifact):\n    return {'score': 0.0 if 'dangerous' in artifact else 1.0}"
AUTH = {"Authorization": "Bearer tsk_abc_def"}


class FakeIntrospector:
    async def introspect(self, api_key: str) -> Principal | None:
        return Principal(organization_id=ORG, key_id="k")

    async def aclose(self) -> None:
        return None


@pytest.fixture
def app():
    return create_app(
        Settings(environment=Environment.CI, region_id="us-east-1", region_locality="na",
                 fast_wall_timeout_s=5.0),
        introspector=FakeIntrospector(), publisher=NullPublisher(),
    )


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ivp") as c:
        yield c


async def _policy(client):
    body = {
        "slug": "default", "project_id": str(uuid.uuid4()),
        "verifiers": [{"verifier_id": str(uuid.uuid4()), "tier": "auto",
                       "definition": {"code": GUARD, "threshold": 1.0}}],
        "thresholds": {"block_at": 0.5},
    }
    r = await client.post("/v1/inline/policies", json=body, headers=AUTH)
    assert r.status_code == 201


async def test_decision_is_stamped_with_region(client):
    await _policy(client)
    r = await client.post("/v1/inline/verify",
                          json={"policy_slug": "default", "content": "this is safe"},
                          headers=AUTH)
    assert r.status_code == 200
    assert r.json()["reasons"]["region"] == "us-east-1"


async def test_slo_records_decisions(app, client):
    await _policy(client)
    await client.post("/v1/inline/verify",
                      json={"policy_slug": "default", "content": "safe"}, headers=AUTH)
    assert app.state.enterprise.slo.total >= 1
    assert app.state.enterprise.slo.attainment() <= 1.0


async def test_chaos_failpoint_degrades_fail_open(app, client):
    await _policy(client)
    # Arm an error at the verify failpoint: fail-open default -> allow but degraded.
    app.state.enterprise.injector.arm("ivp.verify", error=True)
    r = await client.post("/v1/inline/verify",
                          json={"policy_slug": "default", "content": "this is dangerous"},
                          headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "allow"        # fail-open
    assert body["degraded"] is True
    assert body["reasons"]["cause"] == "chaos_failpoint"


async def test_ops_status_endpoint(client):
    r = await client.get("/v1/ops/status")
    assert r.status_code == 200
    body = r.json()
    assert body["region_id"] == "us-east-1"
    assert "slo" in body and "attainment" in body["slo"]
    assert body["resilience"]["breaker_state"] in ("closed", "open", "half_open")
