"""Risk-engine worker.

`process()` handles one ``verification.completed`` envelope: assess risk from the
verification's score + uncertainty + pass/fail, write the risk score back onto
the run, and emit ``risk.scored``. `run()` is the long-lived consumer loop.

Idempotent: re-processing the same completed event recomputes the same risk and
re-writes the same scalar (last-write-wins), and the emitted event carries the
verification id as its idempotency key.
"""

from __future__ import annotations

import asyncio

import structlog
from touchstone_events import (
    EventEnvelope,
    RiskScoredPayload,
    VerificationCompletedPayload,
    new_envelope,
)

from .publisher import Publisher
from .repository import Repository
from .scorer import RiskModel

log = structlog.get_logger(__name__)


class Worker:
    def __init__(
        self, *, repository: Repository, publisher: Publisher,
        model: RiskModel | None = None,
    ) -> None:
        self._repo = repository
        self._publisher = publisher
        self._model = model or RiskModel()

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if not isinstance(payload, VerificationCompletedPayload):
            return  # ignore non-completion events sharing the topic

        assessment = self._model.assess(
            score=payload.score, uncertainty=payload.uncertainty, passed=payload.passed
        )
        await self._repo.set_risk_score(payload.verification_id, assessment.risk_score)

        scored = new_envelope(
            org_id=envelope.org_id,
            workspace_id=envelope.workspace_id,
            trace_id=envelope.trace_id,
            idempotency_key=str(payload.verification_id),
            payload=RiskScoredPayload(
                verification_id=payload.verification_id,
                project_id=payload.project_id,
                risk_score=assessment.risk_score,
                risk_band=assessment.band.value,
                contributing_factors=assessment.factors,
            ),
        )
        await self._publisher.publish(scored)
        log.info(
            "risk.scored",
            verification_id=str(payload.verification_id),
            risk_score=assessment.risk_score,
            band=assessment.band.value,
        )

    async def run(self, brokers: str, group: str, *, max_concurrency: int = 8) -> None:
        from aiokafka import AIOKafkaConsumer
        from touchstone_events import Topic

        consumer = AIOKafkaConsumer(
            Topic.VERIFICATION.value, bootstrap_servers=brokers, group_id=group,
            enable_auto_commit=False, auto_offset_reset="earliest",
        )
        await consumer.start()
        sem = asyncio.Semaphore(max_concurrency)
        log.info("risk_worker.consuming", topic=Topic.VERIFICATION.value, group=group)
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.model_validate_json(msg.value)
                except Exception:
                    log.warning("risk_worker.bad_envelope", offset=msg.offset)
                    await consumer.commit()
                    continue
                if isinstance(envelope.payload, VerificationCompletedPayload):
                    async with sem:
                        await self.process(envelope)
                await consumer.commit()
        finally:
            await consumer.stop()
