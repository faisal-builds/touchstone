"""Tests for the dead-letter queue helpers."""

from __future__ import annotations

import base64
import json

import pytest

from touchstone_events import DeadLetterPublisher, build_dead_letter, dlq_topic


def test_dlq_topic_appends_suffix():
    assert dlq_topic("touchstone.verification.v1") == "touchstone.verification.v1.dlq"


def test_dlq_topic_is_idempotent():
    assert dlq_topic("x.dlq") == "x.dlq"


def test_build_dead_letter_roundtrips_payload_and_metadata():
    raw = b"\x00\x01 not valid json \xff"
    rec = json.loads(
        build_dead_letter(
            source_topic="touchstone.verification.v1",
            raw_value=raw,
            error="boom",
            consumer_group="verification-engine",
            partition=2,
            offset=99,
            attempts=3,
        )
    )
    assert rec["source_topic"] == "touchstone.verification.v1"
    assert rec["consumer_group"] == "verification-engine"
    assert rec["partition"] == 2
    assert rec["offset"] == 99
    assert rec["attempts"] == 3
    assert rec["error"] == "boom"
    assert "failed_at" in rec
    # Original bytes survive intact through base64.
    assert base64.b64decode(rec["payload_b64"]) == raw


@pytest.mark.asyncio
async def test_publisher_sends_to_dlq_topic():
    sent: list[tuple[str, bytes]] = []

    async def fake_send(topic: str, value: bytes):
        sent.append((topic, value))

    pub = DeadLetterPublisher(fake_send, consumer_group="g")
    target = await pub.publish(
        source_topic="touchstone.risk.v1",
        raw_value=b"bad",
        error="oops",
        offset=5,
    )
    assert target == "touchstone.risk.v1.dlq"
    assert len(sent) == 1
    assert sent[0][0] == "touchstone.risk.v1.dlq"
    payload = json.loads(sent[0][1])
    assert payload["offset"] == 5
    assert payload["consumer_group"] == "g"
