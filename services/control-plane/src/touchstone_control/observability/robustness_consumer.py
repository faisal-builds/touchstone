"""Robustness-score consumer (single-writer of ``verifiers.robustness_score``).

The reward-hacking-detector owns robustness *evaluations* in its own database and
no longer writes the control-plane's ``verifiers`` table. Instead it emits a
``reward_hacking.robustness_evaluated`` event; the control-plane — the sole owner
and writer of the ``verifiers`` table — consumes that event here and updates the
denormalized headline ``robustness_score`` the dashboard reads.

This preserves the single-writer invariant after the per-service database split.
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from touchstone_events import EventEnvelope, RobustnessEvaluatedPayload, Topic

from ..db.models import Verifier

log = structlog.get_logger(__name__)


class RobustnessConsumer:
    """Applies robustness scores from RHD events onto the verifier row."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def process(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload
        if not isinstance(payload, RobustnessEvaluatedPayload):
            return
        async with self._sessionmaker() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    update(Verifier)
                    .where(Verifier.id == payload.verifier_id)
                    .values(robustness_score=payload.robustness_score)
                ),
            )
            await session.commit()
        if result.rowcount:
            log.info(
                "control_plane.robustness_applied",
                verifier_id=str(payload.verifier_id),
                robustness_score=payload.robustness_score,
            )
        else:
            # The verifier may belong to another deployment, or was deleted.
            log.warning(
                "control_plane.robustness_verifier_missing",
                verifier_id=str(payload.verifier_id),
            )

    async def run(self, brokers: str, group: str) -> None:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            Topic.REWARD_HACKING.value,
            bootstrap_servers=brokers,
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        log.info(
            "control_plane.robustness_consuming",
            topic=Topic.REWARD_HACKING.value,
            group=group,
        )
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.model_validate_json(msg.value)
                    await self.process(envelope)
                except Exception:  # noqa: BLE001 - never let one bad event stop the loop
                    log.exception("control_plane.robustness_consume_error")
                finally:
                    await consumer.commit()
        finally:
            await consumer.stop()
