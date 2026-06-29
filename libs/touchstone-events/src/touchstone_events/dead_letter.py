"""Dead-letter queue (DLQ) support for Touchstone event consumers.

When a consumer receives a message it can never successfully process — a
malformed envelope, a payload that fails validation, or a poison message that
exhausts its retries — silently dropping it loses an audit trail and hides bugs.
Instead the consumer routes the original bytes, plus diagnostic metadata, to a
dead-letter topic (``<topic>.dlq``) for inspection and replay.

This module is intentionally transport-agnostic: :class:`DeadLetterPublisher`
takes any async ``send(topic, value)`` callable (e.g. an aiokafka producer's
``send_and_wait``), so it is trivial to unit-test and reuse across services.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ["dlq_topic", "build_dead_letter", "DeadLetterPublisher"]

SendFn = Callable[[str, bytes], Awaitable[Any]]


def dlq_topic(topic: str) -> str:
    """Return the dead-letter topic name for a source topic.

    Idempotent: a topic that already ends in ``.dlq`` is returned unchanged so a
    DLQ is never nested into a ``.dlq.dlq``.
    """

    return topic if topic.endswith(".dlq") else f"{topic}.dlq"


def build_dead_letter(
    *,
    source_topic: str,
    raw_value: bytes,
    error: str,
    consumer_group: str | None = None,
    partition: int | None = None,
    offset: int | None = None,
    attempts: int = 1,
) -> bytes:
    """Build the JSON-encoded dead-letter record for a failed message.

    The original bytes are base64-encoded so arbitrary (even non-UTF-8) payloads
    round-trip intact for later replay.
    """

    record = {
        "source_topic": source_topic,
        "consumer_group": consumer_group,
        "partition": partition,
        "offset": offset,
        "attempts": attempts,
        "error": error[:2000],
        "failed_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "payload_b64": base64.b64encode(raw_value).decode("ascii"),
    }
    return json.dumps(record, separators=(",", ":")).encode("utf-8")


class DeadLetterPublisher:
    """Publishes failed messages to the dead-letter topic for their source."""

    def __init__(self, send: SendFn, *, consumer_group: str | None = None) -> None:
        self._send = send
        self._group = consumer_group

    async def publish(
        self,
        *,
        source_topic: str,
        raw_value: bytes,
        error: str,
        partition: int | None = None,
        offset: int | None = None,
        attempts: int = 1,
    ) -> str:
        """Send the dead-letter record; returns the DLQ topic it was sent to."""

        target = dlq_topic(source_topic)
        record = build_dead_letter(
            source_topic=source_topic,
            raw_value=raw_value,
            error=error,
            consumer_group=self._group,
            partition=partition,
            offset=offset,
            attempts=attempts,
        )
        await self._send(target, record)
        return target
