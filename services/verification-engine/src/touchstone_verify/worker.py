"""Verification worker — the heart of the engine.

`process()` handles exactly one ``verification.requested`` envelope end to end:

    load verifier def → build verifier → load artifact → mark RUNNING →
    execute (with timeout) → persist result → publish verification.completed

`run()` is the long-lived Redpanda consumer loop that pulls requests and fans
them out to `process()` under a concurrency bound. Splitting the two means the
per-message logic is fully unit-testable without a broker.

Idempotency: re-processing the same request is safe — the run row is keyed by
id and updates are last-write-wins with identical inputs; the completed event
carries the verification id as its idempotency key.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from touchstone_events import (
    EventEnvelope,
    InlineEscalatedPayload,
    Topic,
    VerificationCompletedPayload,
    VerificationRequestedPayload,
    new_envelope,
)

from .artifact_store import ArtifactStore
from .engine.base import VerifierContext, VerifierError
from .engine.registry import VerifierFactory
from .publisher import Publisher
from .repository import Repository

log = structlog.get_logger(__name__)


class Worker:
    def __init__(
        self,
        *,
        repository: Repository,
        factory: VerifierFactory,
        artifacts: ArtifactStore,
        publisher: Publisher,
        default_timeout_s: float = 30.0,
    ) -> None:
        self._repo = repository
        self._factory = factory
        self._artifacts = artifacts
        self._publisher = publisher
        self._timeout = default_timeout_s

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if isinstance(payload, InlineEscalatedPayload):
            # An IVP escalation: the slow tier runs the verifier exactly like a
            # normal request, against the artifact the plane staged. The deep
            # verdict flows back out as the usual verification.completed event.
            payload = VerificationRequestedPayload(
                verification_id=payload.verification_id,
                verifier_id=payload.verifier_id,
                project_id=payload.project_id,
                artifact_ref=payload.artifact_ref,
                requested_by="ivp:inline",
            )
        if not isinstance(payload, VerificationRequestedPayload):
            log.debug("worker.skip_non_request", type=type(payload).__name__)
            return

        run_id = payload.verification_id
        bind = structlog.contextvars.bound_contextvars(
            verification_id=str(run_id), trace_id=envelope.trace_id
        )
        started = time.perf_counter()
        with bind:
            try:
                record = await self._repo.get_verifier(payload.verifier_id)
                if record is None:
                    raise VerifierError(f"verifier {payload.verifier_id} not found")

                verifier = self._factory.build(record.definition)
                artifact = await self._artifacts.load(payload.artifact_ref)

                await self._repo.mark_running(run_id)
                ctx = VerifierContext(
                    verification_id=str(run_id),
                    verifier_id=str(payload.verifier_id),
                    trace_id=envelope.trace_id,
                    timeout_s=self._timeout,
                )
                result = await asyncio.wait_for(
                    verifier.verify(artifact, ctx), timeout=self._timeout
                )
            except (VerifierError, TimeoutError, Exception) as exc:  # noqa: BLE001
                latency_ms = int((time.perf_counter() - started) * 1000)
                await self._repo.mark_failed(run_id, str(exc), latency_ms)
                log.warning("verification.failed", error=str(exc), latency_ms=latency_ms)
                return

            latency_ms = int((time.perf_counter() - started) * 1000)
            await self._repo.mark_completed(
                run_id,
                score=result.score,
                uncertainty=result.uncertainty,
                passed=result.passed,
                breakdown=result.breakdown,
                latency_ms=latency_ms,
            )
            completed = new_envelope(
                org_id=envelope.org_id,
                workspace_id=envelope.workspace_id,
                trace_id=envelope.trace_id,
                idempotency_key=str(run_id),
                payload=VerificationCompletedPayload(
                    verification_id=run_id,
                    verifier_id=payload.verifier_id,
                    project_id=payload.project_id,
                    score=result.score,
                    uncertainty=result.uncertainty,
                    passed=result.passed,
                    grader_breakdown=result.breakdown,
                    latency_ms=latency_ms,
                ),
            )
            await self._publisher.publish(completed)
            log.info(
                "verification.completed",
                score=round(result.score, 4),
                uncertainty=round(result.uncertainty, 4),
                passed=result.passed,
                latency_ms=latency_ms,
            )

    async def run(self, brokers: str, group: str, *, max_concurrency: int = 8) -> None:
        """Long-lived consumer loop. Imported lazily so unit tests don't need aiokafka."""
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
        from touchstone_events import DeadLetterPublisher

        consumer = AIOKafkaConsumer(
            Topic.VERIFICATION.value,
            Topic.INLINE.value,
            bootstrap_servers=brokers,
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        # Dedicated producer for routing poison messages to the dead-letter topic.
        dlq_producer = AIOKafkaProducer(bootstrap_servers=brokers)
        await dlq_producer.start()
        dlq = DeadLetterPublisher(dlq_producer.send_and_wait, consumer_group=group)
        sem = asyncio.Semaphore(max_concurrency)
        log.info("worker.consuming", topic=Topic.VERIFICATION.value, group=group)
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.model_validate_json(msg.value)
                except Exception as exc:  # noqa: BLE001
                    # Unparseable: route to the DLQ instead of silently dropping.
                    await dlq.publish(
                        source_topic=Topic.VERIFICATION.value,
                        raw_value=msg.value or b"",
                        error=f"envelope validation failed: {exc}",
                        partition=msg.partition,
                        offset=msg.offset,
                    )
                    log.warning("worker.dead_lettered", offset=msg.offset)
                    await consumer.commit()
                    continue

                # Act on verification requests and inline escalations; ignore our
                # own completed events on-topic.
                if not isinstance(
                    envelope.payload, (VerificationRequestedPayload, InlineEscalatedPayload)
                ):
                    await consumer.commit()
                    continue

                async with sem:
                    await self.process(envelope)
                await consumer.commit()
        finally:
            await dlq_producer.stop()
            await consumer.stop()
