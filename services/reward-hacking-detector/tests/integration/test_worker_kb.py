"""Worker + knowledge-base integration test (real sandbox + Postgres).

Drives the full job lifecycle against a weak verifier and asserts:
  * the evaluation row completes with robustness + CI;
  * discovered exploits are persisted to the corpus and deduplicated on re-run
    (occurrences increment, corpus size stable);
  * the robustness score is written back onto the verifier;
  * a robustness.evaluated event is emitted;
  * retries exhaust to a clean ``failed`` status when the orchestrator errors.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_events import EventEnvelope, RobustnessEvaluatedPayload
from touchstone_events import (
    InlineEvasionObservedPayload as _Evasion,
)
from touchstone_events import (
    new_envelope as _new_envelope,
)
from touchstone_verify.sandbox.runner import sandbox_supported

from touchstone_rhd.domain.models import AttackCase
from touchstone_rhd.knowledge.repository import KnowledgeBase, create_schema
from touchstone_rhd.orchestrator import EvaluationConfig, Orchestrator
from touchstone_rhd.worker import AutoEvaluateWorker, EvaluationJobRunner

# Attacks execute verifier code in the real POSIX sandbox; skip — never fail —
# where fork/rlimits are unavailable (Windows). Runs for real in CI on Linux.
pytestmark = pytest.mark.skipif(
    not sandbox_supported(),
    reason="POSIX process sandbox (fork/rlimits/unshare) unavailable on this platform",
)

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"

WEAK_CODE = (
    "def check(artifact):\n"
    "    ok = isinstance(artifact, dict) and 'answer' in artifact\n"
    "    return {'score': 1.0 if ok else 0.0}\n"
)
SEED_CASES = [
    AttackCase(artifact={"answer": 42}, should_pass=True),
    AttackCase(artifact={"answer": 0}, should_pass=False),
]
CONFIG = EvaluationConfig(seed=7, max_attacks=40, max_concurrency=12,
                         per_attack_timeout_s=10.0)


class CollectingPublisher:
    def __init__(self):
        self.events: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.events.append(envelope)


async def _seed_verifier(engine, *, code: str, version: int = 1) -> dict:
    ids = {k: uuid.uuid4() for k in ("org", "ws", "proj", "verifier")}
    # RHD owns its schema and reads verifiers only from its own replica, which in
    # production is fed by the control-plane's `verifier.registered` event.
    await create_schema(engine)
    kb = KnowledgeBase(engine)
    await kb.upsert_verifier_ref(
        verifier_id=ids["verifier"], organization_id=ids["org"], version=version,
        verifier_type="code",
        definition={"code": code, "threshold": 1.0},
    )
    return ids


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(DB_URL)
    yield e
    await e.dispose()


def _runner(engine, publisher=None, *, orch=None, max_retries=3):
    return EvaluationJobRunner(
        kb=KnowledgeBase(engine), orchestrator=orch or Orchestrator(),
        publisher=publisher, max_retries=max_retries, retry_backoff_s=0.01,
    )


@pytest.mark.asyncio
async def test_evaluation_persists_and_writes_back(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE)
    pub = CollectingPublisher()
    runner = _runner(engine, pub)
    kb = KnowledgeBase(engine)

    eval_id = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    result = await runner.run(eval_id, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)

    assert result is not None and result.exploits_found > 0
    row = await kb.get_evaluation(eval_id)
    assert row["status"] == "completed"
    assert row["robustness_score"] is not None
    assert row["ci_low"] <= row["ci_high"]

    # Exploits persisted to the corpus.
    corpus = await kb.list_exploits(ids["verifier"])
    assert len(corpus) == result.exploits_found

    # RHD no longer writes the control-plane's verifier row. Instead it emits the
    # completion event; the control-plane consumes it to update robustness_score.
    assert any(isinstance(e.payload, RobustnessEvaluatedPayload) for e in pub.events)
    evt = next(e for e in pub.events if isinstance(e.payload, RobustnessEvaluatedPayload))
    assert evt.payload.robustness_score == result.robustness_score


@pytest.mark.asyncio
async def test_exploits_deduplicate_across_runs(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE)
    runner = _runner(engine)
    kb = KnowledgeBase(engine)

    e1 = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    await runner.run(e1, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    size_after_first = len(await kb.list_exploits(ids["verifier"]))

    e2 = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    await runner.run(e2, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    corpus = await kb.list_exploits(ids["verifier"])

    # Same attacks => same signatures => no new corpus entries, occurrences bumped.
    assert len(corpus) == size_after_first
    assert any(e["occurrences"] >= 2 for e in corpus)


@pytest.mark.asyncio
async def test_retry_exhaustion_marks_failed(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE)

    class BoomOrchestrator:
        async def evaluate(self, **kw):
            raise RuntimeError("boom")

    runner = _runner(engine, orch=BoomOrchestrator(), max_retries=2)
    kb = KnowledgeBase(engine)
    eval_id = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    result = await runner.run(eval_id, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)

    assert result is None
    row = await kb.get_evaluation(eval_id)
    assert row["status"] == "failed"
    assert "boom" in row["error"]


@pytest.mark.asyncio
async def test_weighted_score_and_version_persisted(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE, version=3)
    runner = _runner(engine)
    kb = KnowledgeBase(engine)
    eval_id = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    result = await runner.run(eval_id, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)

    row = await kb.get_evaluation(eval_id)
    # Weighted robustness persisted and consistent with the result.
    assert row["weighted_robustness_score"] == result.weighted_robustness_score
    # Severity weighting penalizes at least as much as the flat rate.
    assert row["weighted_robustness_score"] <= row["robustness_score"] + 1e-9

    # Exploits are linked to the verifier version they were found against.
    corpus = await kb.list_exploits(ids["verifier"])
    assert corpus and all(e["verifier_version"] == 3 for e in corpus)
    assert all(e["failure_reason"] for e in corpus)


@pytest.mark.asyncio
async def test_search_corpus_filters(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE)
    runner = _runner(engine)
    kb = KnowledgeBase(engine)
    eval_id = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    await runner.run(eval_id, ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)

    org = ids["org"]
    everything = await kb.search_exploits(org)
    assert everything

    # Filter by category returns a subset, all matching.
    a_category = everything[0]["category"]
    by_cat = await kb.search_exploits(org, category=a_category)
    assert by_cat and all(e["category"] == a_category for e in by_cat)
    assert len(by_cat) <= len(everything)

    # Filter by version.
    by_ver = await kb.search_exploits(org, verifier_version=1)
    assert len(by_ver) == len(everything)
    assert not await kb.search_exploits(org, verifier_version=999)

    # Free-text search over strategy name.
    a_strategy = everything[0]["strategy"]
    by_text = await kb.search_exploits(org, query=a_strategy)
    assert by_text and all(a_strategy in e["strategy"] for e in by_text)

    # Pagination.
    page = await kb.search_exploits(org, limit=1, offset=0)
    assert len(page) == 1


@pytest.mark.asyncio
async def test_recover_incomplete_reruns_stranded(engine):
    ids = await _seed_verifier(engine, code=WEAK_CODE)
    runner = _runner(engine)
    kb = KnowledgeBase(engine)

    # Simulate a crash: a launched evaluation that was never run.
    eval_id = await runner.launch(ids["verifier"], config=CONFIG, seed_cases=SEED_CASES)
    pending = await kb.get_evaluation(eval_id)
    assert pending["status"] == "pending"

    recovered = await runner.recover_incomplete()
    assert recovered >= 1
    done = await kb.get_evaluation(eval_id)
    assert done["status"] == "completed"
    assert done["robustness_score"] is not None


@pytest.mark.asyncio
async def test_inline_evasion_triggers_reevaluation(engine):
    """An IVP inline.evasion_observed event re-evaluates the implicated verifier."""
    ids = await _seed_verifier(engine, code=WEAK_CODE)
    pub = CollectingPublisher()
    worker = AutoEvaluateWorker(runner=_runner(engine, pub), config=CONFIG)
    env = _new_envelope(org_id=ids["org"], payload=_Evasion(
        decision_id=uuid.uuid4(), verifier_id=ids["verifier"], project_id=ids["proj"],
        content_sha256="abc", signal="score_cliff", confidence=0.8))

    await worker.process(env)

    # The re-evaluation completed and emitted a robustness.evaluated event.
    robustness = [e for e in pub.events
                  if isinstance(e.payload, RobustnessEvaluatedPayload)]
    assert len(robustness) == 1
    assert robustness[0].payload.verifier_id == ids["verifier"]


@pytest.mark.asyncio
async def test_inline_evasion_unknown_verifier_is_noop(engine):
    await create_schema(engine)
    pub = CollectingPublisher()
    worker = AutoEvaluateWorker(runner=_runner(engine, pub), config=CONFIG)
    env = _new_envelope(org_id=uuid.uuid4(), payload=_Evasion(
        decision_id=uuid.uuid4(), verifier_id=uuid.uuid4(), project_id=uuid.uuid4(),
        content_sha256="abc", signal="budget_exhaustion", confidence=0.5))

    await worker.process(env)  # no such verifier in the replica -> no-op
    assert pub.events == []
