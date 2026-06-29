"""Event producer (ADR-006).

Thin, typed wrapper over aiokafka that publishes `EventEnvelope`s to their
canonical topic. Partitioning is by ``org_id`` so all events for a tenant land
on the same partition, preserving per-tenant ordering for the audit chain.

In tests and local dev without a broker, set ``enabled=False`` to make this a
no-op so the API still functions end-to-end.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from aiokafka import AIOKafkaProducer
from touchstone_events import (
    AuditAction,
    ControlPlaneActionPayload,
    EventEnvelope,
    new_envelope,
)

log = structlog.get_logger(__name__)


class EventProducer:
    def __init__(self, brokers: str, *, enabled: bool = True) -> None:
        self._brokers = brokers
        self._enabled = enabled
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        if not self._enabled:
            log.info("event_producer.disabled")
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._brokers,
            enable_idempotence=True,  # exactly-once semantics on the producer side
            acks="all",
            linger_ms=5,
            compression_type="lz4",
        )
        await self._producer.start()
        log.info("event_producer.started", brokers=self._brokers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def publish(self, envelope: EventEnvelope) -> None:
        if not self._enabled or self._producer is None:
            log.debug("event_producer.noop", topic=envelope.topic().value)
            return
        await self._producer.send_and_wait(
            topic=envelope.topic().value,
            key=str(envelope.org_id).encode(),
            value=envelope.model_dump_json().encode(),
        )


async def publish_control_plane_action(
    producer: EventProducer,
    *,
    org_id: UUID,
    action: AuditAction,
    actor_type: str,
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Publish an auditable control-plane action for the audit-engine to record.

    Best-effort: a publish failure must never fail the user's request, so callers
    invoke this after the action has been committed.
    """
    envelope = new_envelope(
        org_id=org_id,
        trace_id=trace_id,
        payload=ControlPlaneActionPayload(
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata or {},
        ),
    )
    await producer.publish(envelope)
