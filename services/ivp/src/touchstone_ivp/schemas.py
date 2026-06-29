"""IVP wire + domain models.

These define the inline contract: a **Policy** (which verifiers to run on live
traffic, the thresholds that map risk to an action, the latency budget, and the
fail mode), the **request** a caller sends, and the **Decision** the plane returns.
Content is hashed (never logged or emitted) so the audit trail and event bus never
hold customer payloads.
"""

from __future__ import annotations

import enum
import hashlib
import uuid

from pydantic import BaseModel, ConfigDict, Field


class Action(str, enum.Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"
    ESCALATE = "escalate"


class Tier(str, enum.Enum):
    FAST = "fast"      # deterministic, runs inline within the budget
    SLOW = "slow"      # model/process verifier — escalated to the async tier
    AUTO = "auto"      # let the plane decide based on the definition


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class InlineVerifierRef(BaseModel):
    """A verifier bound into a policy for inline execution.

    Carries the verifier definition (so the fast tier can run it without a
    round-trip to the registry) and its robustness score (fed from the RHD) so the
    plane can weight or route around gameable verifiers.
    """

    model_config = ConfigDict(extra="forbid")

    verifier_id: uuid.UUID
    tier: Tier = Tier.AUTO
    # Code-verifier definition for the fast tier; absent => slow/escalate only.
    definition: dict | None = None
    # 0..1 from the RHD; None == unknown. Verifiers below the policy's
    # min_robustness are excluded from the inline decision.
    robustness_score: float | None = None
    # Critical verifiers must pass for an allow regardless of weighted aggregate.
    critical: bool = False


class ActionThresholds(BaseModel):
    """Risk thresholds that map an aggregate risk score to an action.

    Evaluated high-to-low: block first, then redact. Escalation is decided
    separately (a slow verifier was required, or confidence was too low).
    """

    model_config = ConfigDict(extra="forbid")

    block_at: float = Field(default=0.75, ge=0.0, le=1.0)
    redact_at: float | None = Field(default=None, ge=0.0, le=1.0)
    # If the weighted uncertainty exceeds this, escalate to the slow tier.
    escalate_uncertainty_at: float | None = Field(default=None, ge=0.0, le=1.0)


class RedactionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str               # regex
    replacement: str = "[REDACTED]"


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    slug: str
    org_id: uuid.UUID
    project_id: uuid.UUID
    verifiers: list[InlineVerifierRef] = Field(default_factory=list)
    thresholds: ActionThresholds = Field(default_factory=ActionThresholds)
    latency_budget_ms: float | None = None
    fail_mode: str | None = None        # "open" | "closed"; None => plane default
    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    # Exclude verifiers whose robustness score is below this (route around
    # gameable graders). None => include all.
    min_robustness: float | None = None
    redaction_rules: list[RedactionRule] = Field(default_factory=list)
    # Bumped on every change; the plane caches by (policy_id, epoch) so a config
    # push invalidates cleanly across regions.
    epoch: int = 0


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str
    project_id: uuid.UUID
    verifiers: list[InlineVerifierRef] = Field(default_factory=list)
    thresholds: ActionThresholds = Field(default_factory=ActionThresholds)
    latency_budget_ms: float | None = None
    fail_mode: str | None = None
    sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    min_robustness: float | None = None
    redaction_rules: list[RedactionRule] = Field(default_factory=list)


class InlineVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: uuid.UUID | None = None
    policy_slug: str | None = None
    # The live AI output under inspection.
    content: str
    # Optional structured context (model, prompt id, agent step) — never the
    # prompt text itself unless the caller opts in.
    context: dict = Field(default_factory=dict)
    latency_budget_ms: float | None = None
    mode: str = "enforce"     # "enforce" | "shadow"
    idempotency_key: str | None = None


class VerifierOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verifier_id: uuid.UUID
    tier: Tier
    score: float | None = None
    uncertainty: float | None = None
    passed: bool | None = None
    weight: float = 1.0
    critical: bool = False
    latency_ms: float = 0.0
    cached: bool = False
    error: str | None = None
    escalated: bool = False


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    action: Action
    risk_score: float
    risk_band: str
    reasons: dict = Field(default_factory=dict)
    outcomes: list[VerifierOutcome] = Field(default_factory=list)
    latency_ms: float = 0.0
    content_sha256: str
    mode: str = "enforce"
    # Present only when action == redact.
    redacted_content: str | None = None
    # Present when action == escalate: how to fetch the deep verdict.
    escalation: dict | None = None
    degraded: bool = False     # a fail-open/closed fallback was applied
