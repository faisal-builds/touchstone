"""Touchstone event contracts.

This package is the single source of truth for every event that crosses a
service boundary on the Redpanda backbone. Producers and consumers in
`control-plane`, `verification-engine`, `risk-engine`, `audit-engine`, and
`reward-hacking-detector` all import these models so the wire format can never
drift between services.

Design rules (frozen, ADR-006 / ADR-014):
  * Every event is wrapped in `EventEnvelope`. Payloads are versioned.
  * Envelopes are immutable and JSON-serializable.
  * Topic names are centralized in `Topic` so a typo can't silently create a
    new Kafka topic in production.
  * `idempotency_key` lets every consumer dedupe; consumers MUST be idempotent.
"""

from __future__ import annotations

import datetime as _dt
import enum
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Topic",
    "EventType",
    "EventEnvelope",
    "VerificationRequestedPayload",
    "VerificationCompletedPayload",
    "RiskScoredPayload",
    "RewardHackFlaggedPayload",
    "RobustnessEvaluatedPayload",
    "AuditRecordedPayload",
    "ControlPlaneActionPayload",
    "InlineDecisionPayload",
    "InlineEscalatedPayload",
    "InlineEvasionObservedPayload",
    "AuditAction",
    "new_envelope",
    "DeadLetterPublisher",
    "build_dead_letter",
    "dlq_topic",
]


class Topic(str, enum.Enum):
    """Canonical Redpanda topic names. Never hand-write a topic string."""

    VERIFICATION = "touchstone.verification.v1"
    RISK = "touchstone.risk.v1"
    AUDIT = "touchstone.audit.v1"
    REWARD_HACKING = "touchstone.reward_hacking.v1"
    CONTROL_PLANE = "touchstone.control_plane.v1"
    INLINE = "touchstone.inline.v1"


class EventType(str, enum.Enum):
    """Discriminator for envelope payloads."""

    VERIFICATION_REQUESTED = "verification.requested"
    VERIFICATION_COMPLETED = "verification.completed"
    RISK_SCORED = "risk.scored"
    REWARD_HACK_FLAGGED = "reward_hacking.flagged"
    ROBUSTNESS_EVALUATED = "reward_hacking.robustness_evaluated"
    AUDIT_RECORDED = "audit.recorded"
    # control-plane lifecycle
    ORG_CREATED = "control_plane.org.created"
    API_KEY_REVOKED = "control_plane.api_key.revoked"
    # Generic auditable control-plane action (signup, login, key/verifier create…).
    CONTROL_PLANE_ACTION = "control_plane.action"
    # Inline Verification Plane (IVP): enforced live-traffic decisions, escalations
    # to the async tier, and observed evasion attempts that feed the RHD corpus.
    INLINE_DECISION = "inline.decision"
    INLINE_ESCALATED = "inline.escalated"
    INLINE_EVASION_OBSERVED = "inline.evasion_observed"


class AuditAction(str, enum.Enum):
    """Specific auditable actions carried by a ControlPlaneActionPayload."""

    USER_SIGNUP = "user.signup"
    USER_LOGIN = "user.login"
    API_KEY_CREATED = "api_key.created"
    VERIFIER_REGISTERED = "verifier.registered"


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VerificationRequestedPayload(_Payload):
    event_type: Literal[EventType.VERIFICATION_REQUESTED] = EventType.VERIFICATION_REQUESTED
    verification_id: uuid.UUID
    verifier_id: uuid.UUID
    project_id: uuid.UUID
    # Reference to the artifact under test stored in object storage (S3 key).
    artifact_ref: str
    requested_by: str  # API key id or user id


class VerificationCompletedPayload(_Payload):
    event_type: Literal[EventType.VERIFICATION_COMPLETED] = EventType.VERIFICATION_COMPLETED
    verification_id: uuid.UUID
    verifier_id: uuid.UUID
    project_id: uuid.UUID
    # Normalized in [0, 1]; 1.0 == fully passes the verifier.
    score: float = Field(ge=0.0, le=1.0)
    # Epistemic uncertainty in [0, 1]; high == verifier is unsure.
    uncertainty: float = Field(ge=0.0, le=1.0)
    passed: bool
    grader_breakdown: dict[str, float] = Field(default_factory=dict)
    latency_ms: int = Field(ge=0)


class RiskScoredPayload(_Payload):
    event_type: Literal[EventType.RISK_SCORED] = EventType.RISK_SCORED
    verification_id: uuid.UUID
    project_id: uuid.UUID
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_band: Literal["low", "medium", "high", "critical"]
    contributing_factors: dict[str, float] = Field(default_factory=dict)


class RewardHackFlaggedPayload(_Payload):
    event_type: Literal[EventType.REWARD_HACK_FLAGGED] = EventType.REWARD_HACK_FLAGGED
    verification_id: uuid.UUID
    verifier_id: uuid.UUID
    project_id: uuid.UUID
    exploit_signature: str
    confidence: float = Field(ge=0.0, le=1.0)
    detector: str


class RobustnessEvaluatedPayload(_Payload):
    """Emitted when a reward-hacking evaluation of a verifier completes.

    Carries the headline robustness score and exploit count so downstream
    consumers (dashboards, CI gates, audit) can react without querying the DB.
    """

    event_type: Literal[EventType.ROBUSTNESS_EVALUATED] = EventType.ROBUSTNESS_EVALUATED
    verifier_id: uuid.UUID
    evaluation_id: uuid.UUID
    verifier_version: int
    robustness_score: float = Field(ge=0.0, le=1.0)
    exploits_found: int
    is_regression: bool = False


class AuditRecordedPayload(_Payload):
    event_type: Literal[EventType.AUDIT_RECORDED] = EventType.AUDIT_RECORDED
    audit_id: uuid.UUID
    org_id: uuid.UUID
    chain_index: int
    record_hash: str
    prev_hash: str


class ControlPlaneActionPayload(_Payload):
    """A control-plane action worth auditing (signup, login, key/verifier create).

    Generic on purpose: one payload type covers all lightweight lifecycle actions
    so the discriminated union stays small. The specific action is in ``action``.
    """

    event_type: Literal[EventType.CONTROL_PLANE_ACTION] = EventType.CONTROL_PLANE_ACTION
    action: AuditAction
    actor_type: str  # "user" | "api_key" | "system"
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InlineDecisionPayload(_Payload):
    """An enforced inline decision on a piece of live AI traffic.

    Emitted by the IVP for every non-shadow decision so the audit-engine can write
    it to the tamper-evident chain ("prove what the AI was prevented from doing").
    The content itself is never carried — only a content hash — so the event bus
    and audit log never hold customer payloads.
    """

    event_type: Literal[EventType.INLINE_DECISION] = EventType.INLINE_DECISION
    decision_id: uuid.UUID
    policy_id: uuid.UUID
    project_id: uuid.UUID
    action: Literal["allow", "block", "redact", "escalate"]
    risk_score: float = Field(ge=0.0, le=1.0)
    content_sha256: str
    verifier_ids: list[uuid.UUID] = Field(default_factory=list)
    latency_ms: float = Field(ge=0.0)
    mode: Literal["enforce", "shadow"] = "enforce"
    reasons: dict[str, Any] = Field(default_factory=dict)


class InlineEscalatedPayload(_Payload):
    """An inline request whose verdict needs the async/slow tier.

    Carries the artifact reference the IVP staged so the verification-engine can
    pick it up on the existing async path; the deep verdict returns via
    ``verification.completed``.
    """

    event_type: Literal[EventType.INLINE_ESCALATED] = EventType.INLINE_ESCALATED
    decision_id: uuid.UUID
    verification_id: uuid.UUID
    verifier_id: uuid.UUID
    project_id: uuid.UUID
    artifact_ref: str
    content_sha256: str


class InlineEvasionObservedPayload(_Payload):
    """A suspected inline evasion attempt, fed back to the RHD attack corpus.

    Closes the adversarial flywheel: real-world attempts to slip past inline
    verifiers become corpus entries that harden the verifiers over time.
    """

    event_type: Literal[EventType.INLINE_EVASION_OBSERVED] = EventType.INLINE_EVASION_OBSERVED
    decision_id: uuid.UUID
    verifier_id: uuid.UUID
    project_id: uuid.UUID
    content_sha256: str
    signal: str  # what tripped the suspicion (e.g. "score_cliff", "budget_exhaustion")
    confidence: float = Field(ge=0.0, le=1.0)


AnyPayload = (
    VerificationRequestedPayload
    | VerificationCompletedPayload
    | RiskScoredPayload
    | RewardHackFlaggedPayload
    | RobustnessEvaluatedPayload
    | AuditRecordedPayload
    | ControlPlaneActionPayload
    | InlineDecisionPayload
    | InlineEscalatedPayload
    | InlineEvasionObservedPayload
)


class EventEnvelope(BaseModel):
    """Immutable envelope wrapping every cross-service event.

    The envelope carries routing/tenancy/trace metadata so that consumers never
    have to crack open the payload to know who an event belongs to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    # Multi-tenancy: every event is scoped to an org. Audit + RBAC depend on it.
    org_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    occurred_at: _dt.datetime = Field(
        default_factory=lambda: _dt.datetime.now(_dt.UTC)
    )
    # Distributed-trace correlation across the whole verification path.
    trace_id: str | None = None
    # Consumers dedupe on this. Defaults to event_id but producers may override
    # to make retried publishes idempotent.
    idempotency_key: str | None = None
    schema_version: int = 1
    payload: AnyPayload = Field(discriminator="event_type")

    def topic(self) -> Topic:
        """Route the envelope to its canonical topic based on payload type."""
        return _PAYLOAD_TOPIC[type(self.payload)]


_PAYLOAD_TOPIC: dict[type[_Payload], Topic] = {
    VerificationRequestedPayload: Topic.VERIFICATION,
    VerificationCompletedPayload: Topic.VERIFICATION,
    RiskScoredPayload: Topic.RISK,
    RewardHackFlaggedPayload: Topic.REWARD_HACKING,
    RobustnessEvaluatedPayload: Topic.REWARD_HACKING,
    AuditRecordedPayload: Topic.AUDIT,
    ControlPlaneActionPayload: Topic.CONTROL_PLANE,
    InlineDecisionPayload: Topic.INLINE,
    InlineEscalatedPayload: Topic.INLINE,
    InlineEvasionObservedPayload: Topic.INLINE,
}


def new_envelope(
    *,
    org_id: uuid.UUID,
    payload: AnyPayload,
    workspace_id: uuid.UUID | None = None,
    trace_id: str | None = None,
    idempotency_key: str | None = None,
) -> EventEnvelope:
    """Factory ensuring envelopes are always constructed with required tenancy."""
    return EventEnvelope(
        org_id=org_id,
        workspace_id=workspace_id,
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )


# Dead-letter queue helpers (re-exported for convenience).
from .dead_letter import (  # noqa: E402
    DeadLetterPublisher,
    build_dead_letter,
    dlq_topic,
)
