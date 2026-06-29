"""Domain model for the reward-hacking detector.

The conceptual core: a *verifier* maps an artifact to a verdict (pass / score).
A **reward hack** is an artifact that does **not deserve to pass** yet the verifier
passes it — a false positive in the dangerous direction. Reward hacking is
specifically the verifier being too lenient: rewarding low-quality work.

The pipeline produces and consumes these types:

    AttackCase   — a base artifact + ground-truth label (should it pass?).
    AttackVariant— an adversarial transform of a case. Every variant is crafted
                   to be *undeserving* (``expected_pass = False``); the verifier's
                   job is to reject it. Carries the strategy + category that made it.
    AttackOutcome— what the verifier actually did with a variant (passed?, score).
    Exploit      — an outcome where the verifier was fooled (passed an undeserving
                   variant). Carries a stable ``signature`` for dedup + a severity.
    EvaluationResult — the aggregate: robustness score, CI, exploit list.

Keeping these as plain, immutable dataclasses (no I/O) makes the attack,
detection, and scoring logic pure and exhaustively testable.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Any


class ExploitCategory(str, enum.Enum):
    """How the verifier was fooled — the taxonomy of reward-hacking exploits."""

    CONTENT_CORRUPTION = "content_corruption"      # correctness broken, still passed
    JUDGE_MANIPULATION = "judge_manipulation"      # injected instructions/flattery
    LENGTH_BIAS = "length_bias"                    # padding inflated the score
    FORMATTING_EXPLOIT = "formatting_exploit"      # structure hid emptiness
    EDGE_CASE = "edge_case"                        # empty/null/extreme passed
    MODEL_GENERATED = "model_generated"            # LLM-crafted adversarial artifact


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclasses.dataclass(frozen=True, slots=True)
class AttackCase:
    """A base artifact with a ground-truth label, used as attack seed material."""

    artifact: Any
    should_pass: bool
    label: str = "seed"


@dataclasses.dataclass(frozen=True, slots=True)
class AttackVariant:
    """An adversarial artifact. By construction it does not deserve to pass."""

    artifact: Any
    strategy: str
    category: ExploitCategory
    # Ground truth for THIS variant. Attacks are always crafted to be undeserving.
    expected_pass: bool = False
    # Human-readable description of what the attack did (for reports).
    description: str = ""
    # Deterministic ordinal assigned by the generator (for reproducible replay).
    ordinal: int = -1


@dataclasses.dataclass(frozen=True, slots=True)
class AttackOutcome:
    """The verifier's response to one variant."""

    variant: AttackVariant
    verifier_passed: bool
    verifier_score: float
    verifier_uncertainty: float
    errored: bool = False
    error: str | None = None
    # The verifier's own output at the moment it ruled — retained so we can record
    # *why* it failed (which sub-check passed it, what reasoning it gave).
    verifier_breakdown: dict[str, float] = dataclasses.field(default_factory=dict)
    verifier_details: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def is_exploit(self) -> bool:
        """The verifier was fooled: it passed (or scored highly on) an undeserving
        variant. Execution errors are NOT exploits — a verifier that crashes on
        adversarial input is a robustness *concern* but not a reward hack."""
        if self.errored:
            return False
        return self.verifier_passed and not self.variant.expected_pass


@dataclasses.dataclass(frozen=True, slots=True)
class Exploit:
    """A confirmed reward hack, ready to persist into the knowledge base."""

    signature: str
    category: ExploitCategory
    strategy: str
    severity: Severity
    artifact: Any
    verifier_score: float
    description: str
    # Why the verifier failed: a human-readable explanation synthesized from the
    # attack and the verifier's own breakdown/details at the moment it was fooled.
    failure_reason: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    low: float
    high: float
    level: float = 0.95


@dataclasses.dataclass(frozen=True, slots=True)
class EvaluationResult:
    seed: int
    total_attacks: int
    executed: int
    errored: int
    exploits: list[Exploit]
    robustness_score: float
    robustness_ci: ConfidenceInterval
    # Exploit counts broken down by category, for reports.
    category_counts: dict[str, int]
    # Severity-weighted robustness: penalizes critical exploits more than minor
    # ones. The plain robustness_score keeps the (Bernoulli) Wilson CI; this is a
    # complementary, severity-aware view of the same evaluation.
    weighted_robustness_score: float = 1.0

    @property
    def exploits_found(self) -> int:
        return len(self.exploits)
