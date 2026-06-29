"""Risk-engine worker integration test.

Seeds a completed verification run, feeds the worker a ``verification.completed``
envelope, and asserts the run's ``risk_score`` is written and a ``risk.scored``
event is emitted with the correct band.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_events import (
    EventEnvelope,
    RiskScoredPayload,
    VerificationCompletedPayload,
    new_envelope,
)

from touchstone_risk.repository import Repository
from touchstone_risk.worker import Worker

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


class CollectingPublisher:
    def __init__(self):
        self.events: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)


@pytest_asyncio.fixture
async def seeded():
    engine = create_async_engine(DB_URL)
    ids = {k: uuid.uuid4() for k in ("org", "ws", "proj", "verifier", "run")}
    sfx = uuid.uuid4().hex[:8]
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO organizations (id,name,slug,settings,created_at,updated_at)"
            " VALUES (:i,:n,:s,'{}',now(),now())"), {"i": ids["org"], "n": f"O{sfx}", "s": f"o-{sfx}"})
        await c.execute(text("INSERT INTO workspaces (id,organization_id,name,slug,created_at,updated_at)"
            " VALUES (:i,:o,'W','w',now(),now())"), {"i": ids["ws"], "o": ids["org"]})
        await c.execute(text("INSERT INTO projects (id,organization_id,workspace_id,name,slug,created_at,updated_at)"
            " VALUES (:i,:o,:w,'P','p',now(),now())"), {"i": ids["proj"], "o": ids["org"], "w": ids["ws"]})
        await c.execute(text("INSERT INTO verifiers (id,organization_id,project_id,name,slug,version,"
            "verifier_type,definition,is_active,created_at,updated_at)"
            " VALUES (:i,:o,:p,'V','v',1,'code',CAST(:d AS jsonb),true,now(),now())"),
            {"i": ids["verifier"], "o": ids["org"], "p": ids["proj"], "d": json.dumps({"type": "code"})})
        await c.execute(text("INSERT INTO verification_runs (id,organization_id,project_id,verifier_id,"
            "status,artifact_ref,grader_breakdown,created_at,updated_at)"
            " VALUES (:i,:o,:p,:v,'completed','a.json','{}',now(),now())"),
            {"i": ids["run"], "o": ids["org"], "p": ids["proj"], "v": ids["verifier"]})
    await engine.dispose()
    return ids


def _completed_envelope(ids, *, score, uncertainty, passed):
    return new_envelope(
        org_id=ids["org"],
        payload=VerificationCompletedPayload(
            verification_id=ids["run"], verifier_id=ids["verifier"],
            project_id=ids["proj"], score=score, uncertainty=uncertainty,
            passed=passed, grader_breakdown={"code": score}, latency_ms=12,
        ),
    )


async def _risk_of(ids, run_id):
    engine = create_async_engine(DB_URL)
    async with engine.connect() as c:
        row = (await c.execute(
            text("SELECT risk_score FROM verification_runs WHERE id=:i"), {"i": run_id}
        )).first()
    await engine.dispose()
    return row.risk_score


@pytest.mark.asyncio
async def test_low_risk_for_confident_pass(seeded):
    pub = CollectingPublisher()
    worker = Worker(repository=Repository(create_async_engine(DB_URL)), publisher=pub)
    await worker.process(_completed_envelope(seeded, score=1.0, uncertainty=0.0, passed=True))

    assert await _risk_of(seeded, seeded["run"]) == 0.0
    assert len(pub.events) == 1
    payload = pub.events[0].payload
    assert isinstance(payload, RiskScoredPayload)
    assert payload.risk_band == "low"
    assert payload.verification_id == seeded["run"]


@pytest.mark.asyncio
async def test_high_risk_for_uncertain_failure(seeded):
    pub = CollectingPublisher()
    worker = Worker(repository=Repository(create_async_engine(DB_URL)), publisher=pub)
    await worker.process(_completed_envelope(seeded, score=0.1, uncertainty=0.8, passed=False))

    risk = await _risk_of(seeded, seeded["run"])
    assert risk is not None and risk >= 0.5
    assert pub.events[0].payload.risk_band in ("high", "critical")


@pytest.mark.asyncio
async def test_non_completion_event_is_ignored(seeded):
    pub = CollectingPublisher()
    worker = Worker(repository=Repository(create_async_engine(DB_URL)), publisher=pub)
    # A risk.scored event on the same call should be a no-op.
    env = new_envelope(org_id=seeded["org"], payload=RiskScoredPayload(
        verification_id=seeded["run"], project_id=seeded["proj"],
        risk_score=0.5, risk_band="medium", contributing_factors={}))
    await worker.process(env)
    assert pub.events == []
