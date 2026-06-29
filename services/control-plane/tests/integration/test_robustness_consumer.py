"""The control-plane is the sole writer of ``verifiers.robustness_score``.

After the per-service database split, the reward-hacking-detector no longer writes
the verifier row; it emits ``reward_hacking.robustness_evaluated``. This verifies
the control-plane consumer applies that score onto the verifier.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_events import RobustnessEvaluatedPayload, Topic, new_envelope

from touchstone_control.observability.robustness_consumer import RobustnessConsumer

DB_URL = os.environ.get(
    "TOUCHSTONE_DATABASE_URL",
    "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone",
)


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(DB_URL)
    yield e
    await e.dispose()


async def _seed_verifier(engine) -> dict:
    ids = {k: uuid.uuid4() for k in ("org", "ws", "proj", "verifier")}
    sfx = uuid.uuid4().hex[:8]
    org_sql = (
        "INSERT INTO organizations (id,name,slug,settings,created_at,updated_at)"
        " VALUES (:i,:n,:s,'{}',now(),now())"
    )
    ws_sql = (
        "INSERT INTO workspaces (id,organization_id,name,slug,created_at,updated_at)"
        " VALUES (:i,:o,'W','w',now(),now())"
    )
    proj_sql = (
        "INSERT INTO projects (id,organization_id,workspace_id,name,slug,created_at,updated_at)"
        " VALUES (:i,:o,:w,'P','p',now(),now())"
    )
    ver_sql = (
        "INSERT INTO verifiers (id,organization_id,project_id,name,slug,version,"
        "verifier_type,definition,is_active,created_at,updated_at)"
        " VALUES (:i,:o,:p,'V','v',1,'code','{}'::jsonb,true,now(),now())"
    )
    async with engine.begin() as c:
        await c.execute(text(org_sql), {"i": ids["org"], "n": f"O{sfx}", "s": f"o-{sfx}"})
        await c.execute(text(ws_sql), {"i": ids["ws"], "o": ids["org"]})
        await c.execute(text(proj_sql), {"i": ids["proj"], "o": ids["org"], "w": ids["ws"]})
        await c.execute(text(ver_sql), {"i": ids["verifier"], "o": ids["org"], "p": ids["proj"]})
    return ids


async def test_consumer_applies_robustness_score(engine):
    ids = await _seed_verifier(engine)
    consumer = RobustnessConsumer(engine)

    envelope = new_envelope(
        org_id=ids["org"],
        payload=RobustnessEvaluatedPayload(
            verifier_id=ids["verifier"], evaluation_id=uuid.uuid4(),
            verifier_version=1, robustness_score=0.75, exploits_found=3,
        ),
    )
    await consumer.process(envelope)

    async with engine.connect() as c:
        score = (await c.execute(
            text("SELECT robustness_score FROM verifiers WHERE id=:i"),
            {"i": ids["verifier"]},
        )).scalar()
    assert score == pytest.approx(0.75)


async def test_consumer_ignores_unrelated_payloads(engine):
    # A wrong-topic / wrong-payload envelope is a no-op, not an error.
    from touchstone_events import RiskScoredPayload

    envelope = new_envelope(
        org_id=uuid.uuid4(),
        payload=RiskScoredPayload(
            verification_id=uuid.uuid4(), project_id=uuid.uuid4(),
            risk_score=0.1, risk_band="low",
        ),
    )
    await RobustnessConsumer(engine).process(envelope)  # must not raise


def test_consumer_reads_reward_hacking_topic():
    # Guards the topic the consumer subscribes to (RHD's output topic).
    assert Topic.REWARD_HACKING.value == "touchstone.reward_hacking.v1"
