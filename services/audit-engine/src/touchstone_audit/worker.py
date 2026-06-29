"""Audit-engine worker.

Consumes the control-plane, verification, and risk topics and records each
relevant event into the per-org tamper-evident hash chain. One mapping function
turns any supported payload into an `AppendInput`; the repository handles
chaining, ordering, and idempotency. After a new record is chained, an
``audit.recorded`` event is emitted (on the audit topic, which this service does
not consume — no feedback loop).

Covered events (the seven the platform must audit):
  * control-plane: user.signup, user.login, api_key.created, verifier.registered
  * verification.requested  (submission)
  * verification.completed  (completion)
  * risk.scored
"""

from __future__ import annotations

import asyncio

import structlog
from touchstone_events import (
    AuditRecordedPayload,
    ControlPlaneActionPayload,
    EventEnvelope,
    InlineDecisionPayload,
    RiskScoredPayload,
    Topic,
    VerificationCompletedPayload,
    VerificationRequestedPayload,
    new_envelope,
)

from .publisher import NullPublisher, Publisher
from .repository import AppendInput, Repository

log = structlog.get_logger(__name__)

# Topics the audit-engine consumes (NOT the audit topic itself).
CONSUMED_TOPICS = (
    Topic.CONTROL_PLANE.value, Topic.VERIFICATION.value, Topic.RISK.value, Topic.INLINE.value,
)


def envelope_to_append(envelope: EventEnvelope) -> AppendInput | None:
    """Map a supported event envelope to an audit append, or None if not audited."""
    p = envelope.payload
    common = {
        "organization_id": envelope.org_id,
        "source_event_id": envelope.event_id,
        "occurred_at": envelope.occurred_at,
    }

    if isinstance(p, ControlPlaneActionPayload):
        return AppendInput(
            **common, event_type=p.action.value, actor_type=p.actor_type,
            actor_id=p.actor_id, resource_type=p.resource_type,
            resource_id=p.resource_id, metadata=dict(p.metadata),
        )
    if isinstance(p, VerificationRequestedPayload):
        return AppendInput(
            **common, event_type="verification.requested", actor_type="principal",
            actor_id=p.requested_by, resource_type="verification",
            resource_id=str(p.verification_id),
            metadata={"verifier_id": str(p.verifier_id), "project_id": str(p.project_id),
                      "artifact_ref": p.artifact_ref},
        )
    if isinstance(p, VerificationCompletedPayload):
        return AppendInput(
            **common, event_type="verification.completed", actor_type="system",
            resource_type="verification", resource_id=str(p.verification_id),
            metadata={"score": p.score, "uncertainty": p.uncertainty,
                      "passed": p.passed, "latency_ms": p.latency_ms},
        )
    if isinstance(p, RiskScoredPayload):
        return AppendInput(
            **common, event_type="risk.scored", actor_type="system",
            resource_type="verification", resource_id=str(p.verification_id),
            metadata={"risk_score": p.risk_score, "risk_band": p.risk_band,
                      "factors": dict(p.contributing_factors)},
        )
    if isinstance(p, InlineDecisionPayload):
        # The inline plane's enforced verdicts are the compliance record: "prove
        # what the AI was prevented from doing." Content is never carried — only
        # its hash — so the chain holds no customer payloads.
        return AppendInput(
            **common, event_type="inline.decision", actor_type="system",
            resource_type="inline_policy", resource_id=str(p.policy_id),
            metadata={"decision_id": str(p.decision_id), "action": p.action,
                      "risk_score": p.risk_score, "content_sha256": p.content_sha256,
                      "project_id": str(p.project_id), "latency_ms": p.latency_ms,
                      "mode": p.mode, "verifier_ids": [str(v) for v in p.verifier_ids],
                      "reasons": dict(p.reasons)},
        )
    return None


class Worker:
    def __init__(self, *, repository: Repository, publisher: Publisher | None = None) -> None:
        self._repo = repository
        self._publisher = publisher or NullPublisher()

    async def process(self, envelope: EventEnvelope) -> None:
        item = envelope_to_append(envelope)
        if item is None:
            return
        result = await self._repo.append(item)
        if not result.created:
            log.debug("audit.duplicate_ignored", source_event_id=str(envelope.event_id))
            return
        recorded = new_envelope(
            org_id=envelope.org_id,
            trace_id=envelope.trace_id,
            idempotency_key=str(result.record_hash),
            payload=AuditRecordedPayload(
                audit_id=result.audit_id, org_id=envelope.org_id,
                chain_index=result.chain_index, record_hash=result.record_hash,
                prev_hash=result.prev_hash,
            ),
        )
        await self._publisher.publish(recorded)
        log.info("audit.recorded", event_type=item.event_type,
                 chain_index=result.chain_index, org_id=str(envelope.org_id))

    async def run(self, brokers: str, group: str, *, max_concurrency: int = 4) -> None:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            *CONSUMED_TOPICS, bootstrap_servers=brokers, group_id=group,
            enable_auto_commit=False, auto_offset_reset="earliest",
        )
        await consumer.start()
        sem = asyncio.Semaphore(max_concurrency)
        log.info("audit_worker.consuming", topics=list(CONSUMED_TOPICS), group=group)
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.model_validate_json(msg.value)
                except Exception:
                    log.warning("audit_worker.bad_envelope", offset=msg.offset)
                    await consumer.commit()
                    continue
                async with sem:
                    await self.process(envelope)
                await consumer.commit()
        finally:
            await consumer.stop()
