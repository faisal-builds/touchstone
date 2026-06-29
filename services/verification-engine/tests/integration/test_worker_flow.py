"""End-to-end verification-engine integration test.

Exercises the full worker path against a real Postgres: seed an org/project/
verifier and a PENDING run, drop an artifact in the store, hand the worker a
``verification.requested`` envelope, and assert that (a) the run row is updated
to COMPLETED with the right score and (b) a ``verification.completed`` event is
published.

Requires Postgres at TOUCHSTONE_VERIFY_DATABASE_URL with the control-plane
schema migrated.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_events import (
    EventEnvelope,
    InlineEscalatedPayload,
    VerificationCompletedPayload,
    VerificationRequestedPayload,
    new_envelope,
)

from touchstone_verify.artifact_store import ArtifactStore
from touchstone_verify.engine.registry import VerifierFactory
from touchstone_verify.providers.mock import MockProvider
from touchstone_verify.repository import Repository
from touchstone_verify.sandbox.runner import SandboxLimits, SandboxRunner, sandbox_supported
from touchstone_verify.worker import Worker

# The worker grades verifier code in the real POSIX sandbox; skip — never fail —
# where fork/rlimits are unavailable (Windows). Runs for real in CI on Linux.
pytestmark = pytest.mark.skipif(
    not sandbox_supported(),
    reason="POSIX process sandbox (fork/rlimits/unshare) unavailable on this platform",
)

DB_URL = os.environ.get(
    "TOUCHSTONE_VERIFY_DATABASE_URL",
    "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone",
)


class CollectingPublisher:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)


@pytest_asyncio.fixture
async def seeded(tmp_path):
    """Insert org/project/verifier/run, write an artifact; yield ids + store."""
    engine = create_async_engine(DB_URL)
    org_id, proj_id, ws_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    verifier_id, run_id = uuid.uuid4(), uuid.uuid4()
    sfx = uuid.uuid4().hex[:8]
    definition = {
        "type": "code",
        "code": "def check(a):\n return {'score': 1.0 if a.get('answer')==42 else 0.0}",
        "threshold": 1.0,
    }
    async with engine.begin() as c:
        await c.execute(text(
            "INSERT INTO organizations (id,name,slug,settings,created_at,updated_at)"
            " VALUES (:i,:n,:s,'{}',now(),now())"),
            {"i": org_id, "n": f"Org {sfx}", "s": f"org-{sfx}"})
        await c.execute(text(
            "INSERT INTO workspaces (id,organization_id,name,slug,created_at,updated_at)"
            " VALUES (:i,:o,'W','w',now(),now())"),
            {"i": ws_id, "o": org_id})
        await c.execute(text(
            "INSERT INTO projects (id,organization_id,workspace_id,name,slug,created_at,updated_at)"
            " VALUES (:i,:o,:w,'P','p',now(),now())"),
            {"i": proj_id, "o": org_id, "w": ws_id})
        await c.execute(text(
            "INSERT INTO verifiers (id,organization_id,project_id,name,slug,version,"
            "verifier_type,definition,is_active,created_at,updated_at)"
            " VALUES (:i,:o,:p,'V','v',1,'code',CAST(:d AS jsonb),true,now(),now())"),
            {"i": verifier_id, "o": org_id, "p": proj_id,
             "d": __import__("json").dumps(definition)})
        await c.execute(text(
            "INSERT INTO verification_runs (id,organization_id,project_id,verifier_id,"
            "status,artifact_ref,grader_breakdown,created_at,updated_at)"
            " VALUES (:i,:o,:p,:v,'pending','run.json','{}',now(),now())"),
            {"i": run_id, "o": org_id, "p": proj_id, "v": verifier_id})
    await engine.dispose()

    store = ArtifactStore(f"file://{tmp_path}")
    await store.save("run.json", {"answer": 42})
    yield {"org": org_id, "project": proj_id, "verifier": verifier_id,
           "run": run_id, "store": store}


def _make_worker(store) -> tuple[Worker, CollectingPublisher]:
    engine = create_async_engine(DB_URL)
    factory = VerifierFactory(
        sandbox=SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5)),
        provider=MockProvider(),
    )
    pub = CollectingPublisher()
    worker = Worker(repository=Repository(engine), factory=factory,
                    artifacts=store, publisher=pub, default_timeout_s=15)
    return worker, pub


@pytest.mark.asyncio
async def test_worker_completes_passing_verification(seeded):
    worker, pub = _make_worker(seeded["store"])
    envelope = new_envelope(
        org_id=seeded["org"],
        payload=VerificationRequestedPayload(
            verification_id=seeded["run"], verifier_id=seeded["verifier"],
            project_id=seeded["project"], artifact_ref="run.json",
            requested_by="test"),
    )
    await worker.process(envelope)

    # (a) run row updated
    engine = create_async_engine(DB_URL)
    async with engine.connect() as c:
        row = (await c.execute(text(
            "SELECT status,score,passed,uncertainty,latency_ms FROM verification_runs"
            " WHERE id=:i"), {"i": seeded["run"]})).first()
    await engine.dispose()
    assert row.status == "completed"
    assert row.score == 1.0
    assert row.passed is True
    assert row.latency_ms is not None and row.latency_ms >= 0

    # (b) completed event emitted with matching score
    assert len(pub.events) == 1
    payload = pub.events[0].payload
    assert isinstance(payload, VerificationCompletedPayload)
    assert payload.verification_id == seeded["run"]
    assert payload.score == 1.0 and payload.passed is True


@pytest.mark.asyncio
async def test_worker_processes_inline_escalation(seeded):
    """An IVP inline.escalated event runs the slow tier and emits a completed verdict."""
    worker, pub = _make_worker(seeded["store"])
    envelope = new_envelope(
        org_id=seeded["org"],
        payload=InlineEscalatedPayload(
            decision_id=uuid.uuid4(), verification_id=seeded["run"],
            verifier_id=seeded["verifier"], project_id=seeded["project"],
            artifact_ref="run.json", content_sha256="deadbeef"),
    )
    await worker.process(envelope)

    engine = create_async_engine(DB_URL)
    async with engine.connect() as c:
        row = (await c.execute(text(
            "SELECT status,score,passed FROM verification_runs WHERE id=:i"),
            {"i": seeded["run"]})).first()
    await engine.dispose()
    assert row.status == "completed"
    assert row.score == 1.0 and row.passed is True

    assert len(pub.events) == 1
    payload = pub.events[0].payload
    assert isinstance(payload, VerificationCompletedPayload)
    assert payload.verification_id == seeded["run"]


@pytest.mark.asyncio
async def test_worker_marks_failed_on_missing_artifact(seeded):
    worker, pub = _make_worker(seeded["store"])
    envelope = new_envelope(
        org_id=seeded["org"],
        payload=VerificationRequestedPayload(
            verification_id=seeded["run"], verifier_id=seeded["verifier"],
            project_id=seeded["project"], artifact_ref="does-not-exist.json",
            requested_by="test"),
    )
    await worker.process(envelope)

    engine = create_async_engine(DB_URL)
    async with engine.connect() as c:
        row = (await c.execute(text(
            "SELECT status,error FROM verification_runs WHERE id=:i"),
            {"i": seeded["run"]})).first()
    await engine.dispose()
    assert row.status == "failed"
    assert row.error
    assert pub.events == []  # nothing published on failure
