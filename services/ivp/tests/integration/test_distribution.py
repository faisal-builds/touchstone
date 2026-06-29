"""Global policy distribution: a policy in the log resolves via the region replica."""

from __future__ import annotations

import uuid

import httpx
import pytest

from touchstone_ivp.auth import Principal
from touchstone_ivp.config import Environment, Settings
from touchstone_ivp.distribution import GlobalPolicyDistribution
from touchstone_ivp.events import NullPublisher
from touchstone_ivp.main import create_app
from touchstone_ivp.policy import PolicyEngine, PolicyStore, RobustnessCache
from touchstone_ivp.schemas import (
    ActionThresholds,
    InlineVerifierRef,
    Policy,
    Tier,
)

ORG = uuid.uuid4()
GUARD = "def check(artifact):\n    return {'score': 0.0 if 'dangerous' in artifact else 1.0}"
AUTH = {"Authorization": "Bearer tsk_abc_def"}


class FakeIntrospector:
    async def introspect(self, api_key: str) -> Principal | None:
        return Principal(organization_id=ORG, key_id="k")

    async def aclose(self) -> None:
        return None


def _remote_policy(slug: str) -> Policy:
    return Policy(
        slug=slug, org_id=ORG, project_id=uuid.uuid4(),
        verifiers=[InlineVerifierRef(verifier_id=uuid.uuid4(), tier=Tier.AUTO,
                                     definition={"code": GUARD, "threshold": 1.0})],
        thresholds=ActionThresholds(block_at=0.5),
    )


async def test_loader_resolves_policy_published_in_another_region():
    # A distribution whose log already holds a policy this region never created
    # locally (i.e. authored in another region and propagated).
    dist = GlobalPolicyDistribution("eu-west-1")
    remote = _remote_policy("global-default")
    dist.publish(remote)

    engine = PolicyEngine(PolicyStore(loader=dist.loader), RobustnessCache())
    app = create_app(
        Settings(environment=Environment.CI, region_id="eu-west-1", fast_wall_timeout_s=5.0),
        introspector=FakeIntrospector(), publisher=NullPublisher(), policy_engine=engine,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ivp") as c:
        # The local store has nothing; resolution must go through the replica loader.
        r = await c.post("/v1/inline/verify",
                         json={"policy_slug": "global-default", "content": "this is safe"},
                         headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "allow"
    assert dist.converged() is True


async def test_loader_returns_none_for_unknown_policy():
    dist = GlobalPolicyDistribution("us-east-1")
    got = await dist.loader(ORG, policy_slug="does-not-exist")
    assert got is None


async def test_distribution_enabled_app_publishes_on_create():
    app = create_app(
        Settings(environment=Environment.CI, region_id="us-east-1",
                 distribution_enabled=True, fast_wall_timeout_s=5.0),
        introspector=FakeIntrospector(), publisher=NullPublisher(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ivp") as c:
        body = {
            "slug": "created-here", "project_id": str(uuid.uuid4()),
            "verifiers": [{"verifier_id": str(uuid.uuid4()), "tier": "auto",
                           "definition": {"code": GUARD, "threshold": 1.0}}],
            "thresholds": {"block_at": 0.5},
        }
        created = await c.post("/v1/inline/policies", json=body, headers=AUTH)
        assert created.status_code == 201
    # The create propagated to the global log.
    assert app.state.distribution.log.generation >= 1


@pytest.mark.parametrize("slug", ["a", "b"])
async def test_publish_then_loader_roundtrip(slug):
    dist = GlobalPolicyDistribution("ap-south-1")
    dist.publish(_remote_policy(slug))
    got = await dist.loader(ORG, policy_slug=slug)
    assert got is not None and got.slug == slug
