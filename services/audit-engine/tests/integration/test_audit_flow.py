"""Audit-engine integration test (real Postgres).

Feeds the worker the full sequence of auditable events for one org, then asserts:
  * a gap-free, verifiable hash chain is built (one record per event);
  * all eight audited event types are captured;
  * re-delivering an event is idempotent (no duplicate record);
  * export returns the ordered chain and `verify_chain` confirms integrity;
  * tampering with a stored record is detected by re-verification.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_events import (
    AuditAction,
    ControlPlaneActionPayload,
    InlineDecisionPayload,
    RiskScoredPayload,
    VerificationCompletedPayload,
    VerificationRequestedPayload,
    new_envelope,
)

from touchstone_audit.chain import verify_chain
from touchstone_audit.repository import Repository, create_schema
from touchstone_audit.worker import Worker

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


@pytest_asyncio.fixture
async def org_id():
    """A fresh org id for a chain. The audit-engine owns and creates its own
    schema; ``audit_records`` is FK-free, so no control-plane rows are needed."""
    engine = create_async_engine(DB_URL)
    await create_schema(engine)
    await engine.dispose()
    return uuid.uuid4()


def _events(org_id):
    vid, vfid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return [
        new_envelope(org_id=org_id, payload=ControlPlaneActionPayload(
            action=AuditAction.USER_SIGNUP, actor_type="user", actor_id="u1",
            resource_type="organization", resource_id=str(org_id))),
        new_envelope(org_id=org_id, payload=ControlPlaneActionPayload(
            action=AuditAction.USER_LOGIN, actor_type="user", actor_id="u1")),
        new_envelope(org_id=org_id, payload=ControlPlaneActionPayload(
            action=AuditAction.API_KEY_CREATED, actor_type="user", actor_id="u1",
            resource_type="api_key", resource_id="k1")),
        new_envelope(org_id=org_id, payload=ControlPlaneActionPayload(
            action=AuditAction.VERIFIER_REGISTERED, actor_type="user", actor_id="u1",
            resource_type="verifier", resource_id=str(vfid))),
        new_envelope(org_id=org_id, payload=VerificationRequestedPayload(
            verification_id=vid, verifier_id=vfid, project_id=pid,
            artifact_ref="a.json", requested_by="k1")),
        new_envelope(org_id=org_id, payload=VerificationCompletedPayload(
            verification_id=vid, verifier_id=vfid, project_id=pid, score=1.0,
            uncertainty=0.0, passed=True, grader_breakdown={}, latency_ms=5)),
        new_envelope(org_id=org_id, payload=RiskScoredPayload(
            verification_id=vid, project_id=pid, risk_score=0.0,
            risk_band="low", contributing_factors={})),
        new_envelope(org_id=org_id, payload=InlineDecisionPayload(
            decision_id=uuid.uuid4(), policy_id=uuid.uuid4(), project_id=pid,
            action="block", risk_score=0.91, content_sha256="deadbeef",
            verifier_ids=[vfid], latency_ms=7.5, mode="enforce",
            reasons={"band": "critical"})),
    ]


@pytest.mark.asyncio
async def test_full_chain_is_built_and_verifiable(org_id):
    repo = Repository(create_async_engine(DB_URL))
    worker = Worker(repository=repo)
    events = _events(org_id)
    for env in events:
        await worker.process(env)

    records = await repo.export_org(org_id)
    assert len(records) == 8
    # Gap-free indices 0..7
    assert [r["chain_index"] for r in records] == list(range(8))
    # All seven audited event types present, in order.
    assert [r["event_type"] for r in records] == [
        "user.signup", "user.login", "api_key.created", "verifier.registered",
        "verification.requested", "verification.completed", "risk.scored",
        "inline.decision",
    ]
    # The chain verifies.
    assert verify_chain(records).ok


@pytest.mark.asyncio
async def test_redelivery_is_idempotent(org_id):
    repo = Repository(create_async_engine(DB_URL))
    worker = Worker(repository=repo)
    env = _events(org_id)[0]
    await worker.process(env)
    await worker.process(env)  # same event_id again
    records = await repo.export_org(org_id)
    assert len(records) == 1  # not duplicated


@pytest.mark.asyncio
async def test_tampering_is_detected(org_id):
    repo = Repository(create_async_engine(DB_URL))
    worker = Worker(repository=repo)
    for env in _events(org_id)[:3]:
        await worker.process(env)

    # Tamper: edit a committed record's metadata directly in the DB.
    engine = create_async_engine(DB_URL)
    async with engine.begin() as c:
        await c.execute(text(
            "UPDATE audit_records SET metadata = '{\"tampered\": true}'::jsonb "
            "WHERE organization_id=:o AND chain_index=1"), {"o": org_id})
    await engine.dispose()

    records = await repo.export_org(org_id)
    result = verify_chain(records)
    assert not result.ok
    assert result.broken_at_index == 1
