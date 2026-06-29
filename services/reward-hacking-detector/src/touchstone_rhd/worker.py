"""Evaluation job runner and worker.

``EvaluationJobRunner`` is the background-job core shared by the HTTP API (which
schedules jobs) and the event consumer (which auto-evaluates newly registered
verifiers). It owns the full persisted lifecycle:

    create (pending) ─▶ mark running ─▶ orchestrate ─▶ complete (+corpus+writeback)
                                     └▶ on error: retry with backoff ─▶ fail

Resilience:
  * **Retry** — transient failures (e.g. a flaky provider) are retried up to
    ``max_retries`` with linear backoff before the evaluation is marked failed.
  * **Failure recovery** — ``recover_incomplete`` re-runs evaluations left in
    ``pending``/``running`` by a crashed worker, so no launched evaluation is
    silently lost.
  * **Event integration** — on completion a ``robustness.evaluated`` event is
    published (with a regression flag computed against the previous version), and
    the consumer auto-launches an evaluation when a verifier is registered.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from touchstone_events import (
    AuditAction,
    ControlPlaneActionPayload,
    EventEnvelope,
    InlineEvasionObservedPayload,
    RobustnessEvaluatedPayload,
    Topic,
    new_envelope,
)

from .domain.models import AttackCase, EvaluationResult
from .knowledge.repository import KnowledgeBase
from .orchestrator import EvaluationConfig, Orchestrator
from .publisher import NullPublisher, Publisher
from .scoring.robustness import RobustnessScorer

log = structlog.get_logger(__name__)


def _dump_cases(cases: list[AttackCase]) -> str:
    """ASCII-safe JSON for seed cases (so they survive in the JSONB config)."""
    return json.dumps(
        [{"artifact": c.artifact, "should_pass": c.should_pass, "label": c.label}
         for c in cases],
        ensure_ascii=True, default=str,
    )


def _load_cases(blob: str | None) -> list[AttackCase]:
    if not blob:
        return []
    return [
        AttackCase(artifact=d["artifact"], should_pass=d["should_pass"],
                   label=d.get("label", "seed"))
        for d in json.loads(blob)
    ]


class EvaluationJobRunner:
    def __init__(
        self,
        *,
        kb: KnowledgeBase,
        orchestrator: Orchestrator,
        publisher: Publisher | None = None,
        max_retries: int = 3,
        retry_backoff_s: float = 2.0,
        detector_name: str = "touchstone-rhd",
    ) -> None:
        self._kb = kb
        self._orch = orchestrator
        self._publisher = publisher or NullPublisher()
        self._max_retries = max_retries
        self._backoff = retry_backoff_s
        self._scorer = RobustnessScorer()
        self._detector_name = detector_name

    @property
    def kb(self) -> KnowledgeBase:
        return self._kb

    async def launch(
        self,
        verifier_id: uuid.UUID,
        *,
        config: EvaluationConfig,
        seed_cases: list[AttackCase],
    ) -> uuid.UUID | None:
        """Create a pending evaluation row. Returns None if the verifier is unknown."""
        info = await self._kb.get_verifier(verifier_id)
        if info is None:
            return None
        eval_id = await self._kb.create_evaluation(
            organization_id=info.organization_id, verifier_id=verifier_id,
            verifier_version=info.version, seed=config.seed,
            config={"max_attacks": config.max_attacks,
                    "max_concurrency": config.max_concurrency,
                    "per_attack_timeout_s": config.per_attack_timeout_s,
                    "enable_model_attacks": config.enable_model_attacks,
                    "seed_cases_json": _dump_cases(seed_cases)},
        )
        return eval_id

    async def run(
        self,
        eval_id: uuid.UUID,
        verifier_id: uuid.UUID,
        *,
        config: EvaluationConfig,
        seed_cases: list[AttackCase],
    ) -> EvaluationResult | None:
        info = await self._kb.get_verifier(verifier_id)
        if info is None:
            await self._kb.fail_evaluation(eval_id, "verifier not found")
            return None

        await self._kb.mark_running(eval_id)
        attempt = 0
        while True:
            try:
                result = await self._orch.evaluate(
                    verifier_definition=info.definition, seed_cases=seed_cases,
                    config=config, evaluation_id=str(eval_id),
                )
                await self._kb.complete_evaluation(
                    eval_id, verifier_id=verifier_id,
                    organization_id=info.organization_id, result=result,
                    verifier_version=info.version,
                )
                await self._emit_completion(info, eval_id, result)
                return result
            except Exception as exc:  # noqa: BLE001 — job boundary: classify + retry
                attempt += 1
                if attempt > self._max_retries:
                    log.error("evaluation.failed", eval_id=str(eval_id), error=str(exc))
                    await self._kb.fail_evaluation(eval_id, str(exc))
                    return None
                log.warning("evaluation.retry", eval_id=str(eval_id),
                            attempt=attempt, error=str(exc))
                await asyncio.sleep(self._backoff * attempt)

    async def launch_and_run(
        self, verifier_id: uuid.UUID, *, config: EvaluationConfig,
        seed_cases: list[AttackCase],
    ) -> uuid.UUID | None:
        eval_id = await self.launch(verifier_id, config=config, seed_cases=seed_cases)
        if eval_id is None:
            return None
        await self.run(eval_id, verifier_id, config=config, seed_cases=seed_cases)
        return eval_id

    async def recover_incomplete(self, *, limit: int = 100) -> int:
        """Re-run evaluations stranded in pending/running by a crash.

        Scans the store for non-terminal evaluations (no caller need pass ids),
        reconstructs the original config and seed cases from the persisted row,
        and re-runs each so no launched evaluation is silently lost. Returns the
        number recovered.
        """
        stranded = await self._kb.list_incomplete_evaluations(limit=limit)
        recovered = 0
        for ev in stranded:
            cfg = ev.get("config") or {}
            config = EvaluationConfig(
                seed=ev["seed"],
                max_attacks=cfg.get("max_attacks"),
                max_concurrency=cfg.get("max_concurrency", 16),
                per_attack_timeout_s=cfg.get("per_attack_timeout_s", 15.0),
                enable_model_attacks=cfg.get("enable_model_attacks", False),
            )
            seed_cases = _load_cases(cfg.get("seed_cases_json"))
            log.info("rhd.recover", eval_id=str(ev["id"]), status=ev["status"])
            await self.run(ev["id"], ev["verifier_id"],
                           config=config, seed_cases=seed_cases)
            recovered += 1
        return recovered

    async def _emit_completion(self, info, eval_id, result: EvaluationResult) -> None:
        # Regression vs the previous version's latest completed evaluation.
        is_regression = False
        if info.version > 1:
            prev = await self._kb.latest_completed_for_version(info.id, info.version - 1)
            if prev and prev.get("robustness_score") is not None:
                old = self._scorer.score(
                    executed=prev["executed"], exploits=prev["exploits_found"])
                new = self._scorer.score(
                    executed=result.executed, exploits=result.exploits_found)
                is_regression = self._scorer.compare(old, new).is_regression
        envelope = new_envelope(
            org_id=info.organization_id,
            idempotency_key=str(eval_id),
            payload=RobustnessEvaluatedPayload(
                verifier_id=info.id, evaluation_id=eval_id,
                verifier_version=info.version,
                robustness_score=result.robustness_score,
                exploits_found=result.exploits_found, is_regression=is_regression,
            ),
        )
        await self._publisher.publish(envelope)


class AutoEvaluateWorker:
    """Consumes verifier-registration events and auto-launches evaluations."""

    def __init__(self, *, runner: EvaluationJobRunner, config: EvaluationConfig) -> None:
        self._runner = runner
        self._config = config

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if isinstance(payload, InlineEvasionObservedPayload):
            # The adversarial flywheel: a real-world attempt to slip past an inline
            # verifier triggers a prioritized re-evaluation of that verifier, so its
            # robustness score updates and the IVP's routing adapts. The verifier
            # must already be replicated into RHD's store (from verifier.registered).
            info = await self._runner.kb.get_verifier(payload.verifier_id)
            if info is None:
                log.debug("rhd.inline_evasion_unknown_verifier",
                          verifier_id=str(payload.verifier_id))
                return
            log.info("rhd.inline_evasion_reeval", verifier_id=str(payload.verifier_id),
                     signal=payload.signal, confidence=payload.confidence)
            await self._runner.launch_and_run(
                payload.verifier_id, config=self._config, seed_cases=[])
            return
        if not isinstance(payload, ControlPlaneActionPayload):
            return
        if payload.action != AuditAction.VERIFIER_REGISTERED or not payload.resource_id:
            return
        verifier_id = uuid.UUID(payload.resource_id)
        # Replicate the verifier facts into RHD's own store from the event, so the
        # evaluation never reads the control-plane database. The control-plane
        # enriches `verifier.registered` with the definition/version/type.
        md = payload.metadata or {}
        definition = md.get("definition")
        if definition is not None:
            await self._runner.kb.upsert_verifier_ref(
                verifier_id=verifier_id,
                organization_id=envelope.org_id,
                version=int(md.get("version", 1)),
                verifier_type=str(md.get("verifier_type", "code")),
                definition=definition,
            )
        log.info("rhd.auto_evaluate", verifier_id=str(verifier_id))
        await self._runner.launch_and_run(
            verifier_id, config=self._config, seed_cases=[])

    async def run(self, brokers: str, group: str) -> None:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            Topic.CONTROL_PLANE.value, Topic.INLINE.value,
            bootstrap_servers=brokers, group_id=group,
            enable_auto_commit=False, auto_offset_reset="earliest",
        )
        await consumer.start()
        log.info("rhd_worker.consuming",
                 topics=[Topic.CONTROL_PLANE.value, Topic.INLINE.value], group=group)
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.model_validate_json(msg.value)
                except Exception:  # noqa: BLE001
                    await consumer.commit()
                    continue
                await self.process(envelope)
                await consumer.commit()
        finally:
            await consumer.stop()
