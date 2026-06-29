"""Verifier Robustness Score.

Robustness is the share of adversarial attempts the verifier correctly resisted:

    robustness = 1 - (exploits / executed_attacks)

Because each attack is a Bernoulli trial (exploit / not), the uncertainty on that
proportion is given by a **Wilson score interval** — the right choice over the
normal approximation when the exploit rate is near 0 or 1 (which it usually is for
strong or broken verifiers respectively). The robustness CI is the reflection of
the exploit-rate CI: ``[1 - rate_high, 1 - rate_low]``.

On top of the point score this module provides the comparison primitives a CI/CD
gate needs: version comparison, regression detection (a statistically meaningful
drop, not noise), and trend direction over a history.
"""

from __future__ import annotations

import dataclasses
import math

from ..domain.models import ConfidenceInterval, Severity

# z for a two-sided 95% interval.
_Z95 = 1.959963984540054

# How much each exploit counts against robustness, by severity. A verifier that
# is fooled into confidently passing garbage (critical) is penalized far more
# than one nudged just over a marginal threshold (low).
_SEVERITY_WEIGHT = {
    Severity.CRITICAL: 1.0,
    Severity.HIGH: 0.7,
    Severity.MEDIUM: 0.4,
    Severity.LOW: 0.2,
}


@dataclasses.dataclass(frozen=True, slots=True)
class RobustnessScore:
    robustness: float
    ci: ConfidenceInterval
    executed: int
    exploits: int


@dataclasses.dataclass(frozen=True, slots=True)
class Comparison:
    delta: float                 # new.robustness - old.robustness
    is_regression: bool          # statistically meaningful drop
    is_improvement: bool
    overlapping_ci: bool
    detail: str


def _wilson(k: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n. Returns (low, high) in [0,1]."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


class RobustnessScorer:
    def __init__(self, *, regression_margin: float = 0.02):
        # A drop smaller than this (and within CI overlap) is treated as noise.
        self._regression_margin = regression_margin

    def score(self, *, executed: int, exploits: int) -> RobustnessScore:
        if executed == 0:
            return RobustnessScore(1.0, ConfidenceInterval(0.0, 1.0), 0, 0)
        rate_low, rate_high = _wilson(exploits, executed)
        robustness = 1.0 - exploits / executed
        ci = ConfidenceInterval(low=round(1.0 - rate_high, 6),
                                high=round(1.0 - rate_low, 6))
        return RobustnessScore(round(robustness, 6), ci, executed, exploits)

    def weighted_score(self, *, executed: int, severities: list[Severity]) -> float:
        """Severity-weighted robustness in [0, 1].

        Each exploit subtracts its severity weight (critical 1.0 … low 0.2) rather
        than a flat 1.0, so the score reflects *how badly* the verifier was fooled,
        not just how often. Clamped at 0 because weighted exploits can, in
        principle, exceed the executed count once weighting is applied (they don't
        here, since weights are ≤ 1, but the clamp makes the contract explicit)."""
        if executed == 0:
            return 1.0
        weighted = sum(_SEVERITY_WEIGHT.get(s, 1.0) for s in severities)
        return round(max(0.0, 1.0 - weighted / executed), 6)

    def compare(self, old: RobustnessScore, new: RobustnessScore) -> Comparison:
        """Compare two evaluations (e.g. two verifier versions)."""
        delta = round(new.robustness - old.robustness, 6)
        overlapping = not (new.ci.high < old.ci.low or old.ci.high < new.ci.low)
        # A regression is a drop beyond the noise margin where the new score's
        # confidence interval does not reach back up to the old point estimate.
        is_regression = (
            delta < -self._regression_margin and new.ci.high < old.robustness
        )
        is_improvement = (
            delta > self._regression_margin and new.ci.low > old.robustness
        )
        if is_regression:
            detail = f"robustness dropped {abs(delta):.3f} (regression)"
        elif is_improvement:
            detail = f"robustness improved {delta:.3f}"
        else:
            detail = "no statistically meaningful change"
        return Comparison(delta, is_regression, is_improvement, overlapping, detail)

    @staticmethod
    def trend(history: list[float]) -> str:
        """Direction of a robustness history (oldest→newest): improving / declining / stable."""
        if len(history) < 2:
            return "insufficient_data"
        # Compare the mean of the first half to the second half.
        mid = len(history) // 2
        first = sum(history[:mid]) / max(1, mid)
        second = sum(history[mid:]) / max(1, len(history) - mid)
        diff = second - first
        if diff > 0.02:
            return "improving"
        if diff < -0.02:
            return "declining"
        return "stable"
