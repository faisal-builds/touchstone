"""Policy resolution + robustness-aware selection."""

from __future__ import annotations

import uuid

import pytest

from touchstone_ivp.policy import PolicyEngine, PolicyNotFound, PolicyStore, RobustnessCache
from touchstone_ivp.schemas import InlineVerifierRef, Policy

ORG = uuid.uuid4()
PROJ = uuid.uuid4()


def _policy(verifiers, **kw) -> Policy:
    return Policy(slug="p", org_id=ORG, project_id=PROJ, verifiers=verifiers, **kw)


async def test_store_get_by_id_and_slug():
    store = PolicyStore()
    p = store.put(_policy([]))
    assert (await store.get(ORG, policy_id=p.id)).id == p.id
    assert (await store.get(ORG, policy_slug="p")).id == p.id
    with pytest.raises(PolicyNotFound):
        await store.get(ORG, policy_id=uuid.uuid4())


async def test_loader_fallback_on_miss():
    target = _policy([])

    async def loader(org, pid, slug):
        return target

    store = PolicyStore(loader=loader)
    got = await store.get(ORG, policy_slug="anything")
    assert got.id == target.id


def test_select_routes_around_gameable_verifier():
    trusted = InlineVerifierRef(verifier_id=uuid.uuid4(), robustness_score=0.9)
    gameable = InlineVerifierRef(verifier_id=uuid.uuid4(), robustness_score=0.3)
    engine = PolicyEngine(PolicyStore())
    policy = _policy([trusted, gameable], min_robustness=0.5)

    selected, routed = engine.select(policy)

    assert [r.verifier_id for r, _ in selected] == [trusted.verifier_id]
    assert routed == [gameable.verifier_id]
    # Weight equals the robustness score.
    assert selected[0][1] == pytest.approx(0.9)


def test_live_robustness_overrides_embedded():
    vid = uuid.uuid4()
    ref = InlineVerifierRef(verifier_id=vid, robustness_score=0.9)
    cache = RobustnessCache()
    cache.set(vid, 0.2)  # RHD just downgraded it
    engine = PolicyEngine(PolicyStore(), cache)
    policy = _policy([ref], min_robustness=0.5)

    selected, routed = engine.select(policy)
    assert routed == [vid]   # live score wins -> routed around
    assert selected == []


def test_unknown_robustness_is_included_with_unit_weight():
    ref = InlineVerifierRef(verifier_id=uuid.uuid4())  # no score
    engine = PolicyEngine(PolicyStore())
    policy = _policy([ref], min_robustness=0.5)
    selected, routed = engine.select(policy)
    assert routed == []
    assert selected[0][1] == 1.0
