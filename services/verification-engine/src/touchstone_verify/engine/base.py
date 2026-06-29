"""Core verification abstractions.

Every verifier family (code, model, process, hybrid) implements one interface:
``Verifier.verify(artifact, ctx) -> VerificationResult``. Keeping the contract
this narrow is what lets the ensemble layer treat heterogeneous graders
uniformly and lets the worker stay ignorant of how any given verifier works.

A ``VerificationResult`` always carries:
  * ``score``       — normalized correctness in [0, 1]
  * ``uncertainty`` — epistemic confidence of the grader itself in [0, 1]
  * ``passed``      — boolean decision (score >= threshold, by default)
  * ``breakdown``   — per-sub-grader scores, for transparency + audit

The split between *score* and *uncertainty* is deliberate and central to the
product: a verifier that is confidently wrong and a verifier that is unsure are
very different risks, and the risk-engine treats them differently.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any, Protocol, runtime_checkable


class VerifierFamily(str, enum.Enum):
    CODE = "code"
    MODEL = "model"
    PROCESS = "process"
    HYBRID = "hybrid"


@dataclasses.dataclass(frozen=True, slots=True)
class VerificationResult:
    score: float
    uncertainty: float
    passed: bool
    breakdown: dict[str, float] = dataclasses.field(default_factory=dict)
    # Free-form diagnostics (sandbox stderr, judge reasoning, failing step index).
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score out of range: {self.score}")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise ValueError(f"uncertainty out of range: {self.uncertainty}")

    @staticmethod
    def clamp(x: float) -> float:
        return max(0.0, min(1.0, x))


@dataclasses.dataclass(frozen=True, slots=True)
class VerifierContext:
    """Carried through execution for tracing/limits. No tenant data leaks here."""

    verification_id: str
    verifier_id: str
    trace_id: str | None = None
    # Hard wall-clock budget for the whole verifier (seconds).
    timeout_s: float = 30.0


@runtime_checkable
class Verifier(Protocol):
    """The single interface every grader implements."""

    family: VerifierFamily

    async def verify(self, artifact: Any, ctx: VerifierContext) -> VerificationResult:
        ...


class VerifierError(Exception):
    """Raised when a verifier cannot produce a result (vs. producing a low score).

    A failed *execution* (sandbox crash, provider outage) is distinct from a
    legitimate *low score*; the worker marks the former as FAILED and the latter
    as COMPLETED.
    """
