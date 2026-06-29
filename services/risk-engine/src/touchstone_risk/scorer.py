"""Risk scoring model.

Turns a completed verification (its ``score`` and ``uncertainty``) into a single
risk value in [0, 1] and a categorical band. The model is deliberately simple,
deterministic, and explainable — risk decisions must be auditable, so this is a
transparent weighted combination rather than an opaque learned function.

Intuition:
  * A *failing* verification (low score) is risky — the AI output is likely wrong.
  * An *uncertain* verification (high uncertainty) is risky regardless of score —
    we cannot trust the verdict, so the output should not be relied upon.
  * A high score with low uncertainty is low risk.

    risk = w_failure * (1 - score) + w_uncertainty * uncertainty

A hard product rule overrides the formula: a verification that did **not pass**
is never classified below the ``medium`` band, because shipping a failed result
is intrinsically risky even if the grader was confident about the failure margin.
"""

from __future__ import annotations

import dataclasses
import enum


class RiskBand(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclasses.dataclass(frozen=True, slots=True)
class RiskAssessment:
    risk_score: float
    band: RiskBand
    factors: dict[str, float]


@dataclasses.dataclass(frozen=True, slots=True)
class RiskModel:
    failure_weight: float = 0.6
    uncertainty_weight: float = 0.4
    # Upper bounds (exclusive) for each band; >= high threshold is critical.
    medium_threshold: float = 0.25
    high_threshold: float = 0.50
    critical_threshold: float = 0.75
    # A non-passing verification is floored to at least this risk score.
    fail_floor: float = 0.50

    def __post_init__(self) -> None:
        total = self.failure_weight + self.uncertainty_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError("failure_weight + uncertainty_weight must equal 1.0")

    @staticmethod
    def _clamp(x: float) -> float:
        return max(0.0, min(1.0, x))

    def band_for(self, risk: float) -> RiskBand:
        if risk < self.medium_threshold:
            return RiskBand.LOW
        if risk < self.high_threshold:
            return RiskBand.MEDIUM
        if risk < self.critical_threshold:
            return RiskBand.HIGH
        return RiskBand.CRITICAL

    def assess(self, *, score: float, uncertainty: float, passed: bool) -> RiskAssessment:
        score = self._clamp(score)
        uncertainty = self._clamp(uncertainty)
        failure = 1.0 - score
        risk = self.failure_weight * failure + self.uncertainty_weight * uncertainty
        risk = self._clamp(risk)
        if not passed:
            risk = max(risk, self.fail_floor)
        return RiskAssessment(
            risk_score=round(risk, 6),
            band=self.band_for(risk),
            factors={
                "failure": round(failure, 6),
                "uncertainty": round(uncertainty, 6),
                "passed": 0.0 if passed else 1.0,
            },
        )
