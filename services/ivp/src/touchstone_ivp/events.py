"""Event integration + artifact staging for the inline plane.

The plane closes three loops over the existing bus, all off the hot path:

* ``inline.decision`` → audit-engine writes it to the tamper-evident chain;
* ``inline.escalated`` → verification-engine produces the deep verdict (the
  content is staged to the shared artifact store first);
* ``inline.evasion_observed`` → RHD folds the attempt into its attack corpus.

Emission and staging happen in the background so a caller never waits on the bus
or object store. ``NullPublisher`` is used in CI (no broker), exactly like the
other services.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from touchstone_events import (
    EventEnvelope,
    InlineDecisionPayload,
    InlineEscalatedPayload,
    InlineEvasionObservedPayload,
    new_envelope,
)

from .schemas import Decision, InlineVerifierRef, Policy


class Publisher(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...


class NullPublisher:
    async def publish(self, envelope: EventEnvelope) -> None:  # noqa: D401
        return None


class Stager(Protocol):
    async def stage(self, org_id: uuid.UUID, content: str) -> str: ...


class LocalStager:
    """Writes inline content to a content-addressed file the engine can read.

    Production injects an S3-backed stager (the same store the verification-engine
    reads); this local one keeps the escalation path real and runnable without S3.
    """

    def __init__(self, root: str = "./.artifacts/inline") -> None:
        self._root = Path(root)

    async def stage(self, org_id: uuid.UUID, content: str) -> str:
        import hashlib
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = f"inline/{org_id}/{digest}.txt"
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return key


class InlineEventEmitter:
    def __init__(self, publisher: Publisher, stager: Stager | None = None) -> None:
        self._pub = publisher
        self._stager = stager or LocalStager()

    async def emit_decision(self, org_id: uuid.UUID, policy: Policy, decision: Decision) -> None:
        if decision.mode != "enforce":
            return  # shadow decisions are not enforced; skip the audit write
        payload = InlineDecisionPayload(
            decision_id=decision.decision_id, policy_id=policy.id, project_id=policy.project_id,
            action=decision.action.value, risk_score=decision.risk_score,
            content_sha256=decision.content_sha256,
            verifier_ids=[o.verifier_id for o in decision.outcomes],
            latency_ms=decision.latency_ms, mode=decision.mode,
            reasons={"band": decision.risk_band, "degraded": decision.degraded},
        )
        await self._pub.publish(new_envelope(org_id=org_id, payload=payload))

    async def emit_escalations(
        self, org_id: uuid.UUID, policy: Policy, decision: Decision,
        content: str, escalations: list[InlineVerifierRef],
    ) -> None:
        if not escalations:
            return
        artifact_ref = await self._stager.stage(org_id, content)
        for ref in escalations:
            payload = InlineEscalatedPayload(
                decision_id=decision.decision_id, verification_id=uuid.uuid4(),
                verifier_id=ref.verifier_id, project_id=policy.project_id,
                artifact_ref=artifact_ref, content_sha256=decision.content_sha256,
            )
            await self._pub.publish(new_envelope(org_id=org_id, payload=payload))

    async def emit_evasion(
        self, org_id: uuid.UUID, policy: Policy, decision: Decision,
        verifier_id: uuid.UUID, signal: str, confidence: float,
    ) -> None:
        payload = InlineEvasionObservedPayload(
            decision_id=decision.decision_id, verifier_id=verifier_id,
            project_id=policy.project_id, content_sha256=decision.content_sha256,
            signal=signal, confidence=confidence,
        )
        await self._pub.publish(new_envelope(org_id=org_id, payload=payload))
