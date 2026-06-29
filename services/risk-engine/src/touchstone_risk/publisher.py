"""Result publisher — emits risk.scored onto the Redpanda backbone.

A `Publisher` Protocol lets tests substitute a collecting fake with no broker.
"""

from __future__ import annotations

from typing import Protocol

from aiokafka import AIOKafkaProducer
from touchstone_events import EventEnvelope


class Publisher(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...


class KafkaPublisher:
    def __init__(self, brokers: str) -> None:
        self._brokers = brokers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._brokers, enable_idempotence=True,
            acks="all", compression_type="lz4",
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def publish(self, envelope: EventEnvelope) -> None:
        assert self._producer is not None, "publisher not started"
        await self._producer.send_and_wait(
            topic=envelope.topic().value,
            key=str(envelope.org_id).encode(),
            value=envelope.model_dump_json().encode(),
        )
