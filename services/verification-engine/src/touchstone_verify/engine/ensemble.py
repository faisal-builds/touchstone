"""Ensemble (hybrid) verifier — meta-verification (see registry.py for the factory).

A single grader is a single point of failure: if a model learns to game it, the
reward signal is silently corrupted. The ensemble runs several independent
sub-verifiers and combines them so that **disagreement raises uncertainty**.
High uncertainty is the signal the risk-engine and reward-hacking-detector key
on to flag a verdict for escalation rather than trusting it blindly.

Definition schema::

    {
        "type": "hybrid",
        "members": [ {<verifier def>}, {<verifier def>}, ... ],
        "weights": [0.5, 0.5],         # optional; defaults to equal
        "threshold": 0.5,
        "escalate_uncertainty": 0.3    # passed=False if uncertainty exceeds this
    }

Combined score is the weighted mean of member scores. Uncertainty is the max of
(a) the weighted dispersion across members and (b) the members' own reported
uncertainties — so we are never more confident than our least confident grader,
and never confident when graders disagree.
"""

from __future__ import annotations

import asyncio
import statistics
from typing import Any

from .base import (
    VerificationResult,
    Verifier,
    VerifierContext,
    VerifierError,
    VerifierFamily,
)


class EnsembleVerifier(Verifier):
    family = VerifierFamily.HYBRID

    def __init__(
        self,
        members: list[Verifier],
        *,
        weights: list[float] | None = None,
        threshold: float = 0.5,
        escalate_uncertainty: float = 0.3,
    ) -> None:
        if not members:
            raise VerifierError("ensemble requires at least one member")
        if weights is not None and len(weights) != len(members):
            raise VerifierError("weights length must match members length")
        self._members = members
        total = sum(weights) if weights else float(len(members))
        self._weights = [w / total for w in (weights or [1.0] * len(members))]
        self._threshold = threshold
        self._escalate = escalate_uncertainty

    async def verify(self, artifact: Any, ctx: VerifierContext) -> VerificationResult:
        # Run members concurrently; a member that errors contributes max
        # uncertainty rather than failing the whole verdict.
        results = await asyncio.gather(
            *(m.verify(artifact, ctx) for m in self._members),
            return_exceptions=True,
        )

        scores: list[float] = []
        member_unc: list[float] = []
        breakdown: dict[str, float] = {}
        errored = 0
        used_weights: list[float] = []
        for i, (res, w) in enumerate(zip(results, self._weights, strict=True)):
            label = f"{self._members[i].family.value}_{i}"
            if isinstance(res, Exception):
                errored += 1
                breakdown[label] = -1.0  # sentinel: grader failed
                continue
            scores.append(res.score)
            member_unc.append(res.uncertainty)
            used_weights.append(w)
            breakdown[label] = res.score

        if not scores:
            raise VerifierError("all ensemble members failed")

        wsum = sum(used_weights) or 1.0
        combined = sum(s * w for s, w in zip(scores, used_weights, strict=True)) / wsum

        dispersion = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        # Penalize uncertainty when graders disagree, when members are unsure,
        # and when some members failed outright.
        failure_penalty = errored / len(self._members)
        uncertainty = VerificationResult.clamp(
            max(dispersion * 2, max(member_unc, default=0.0), failure_penalty)
        )

        passed = combined >= self._threshold and uncertainty <= self._escalate
        return VerificationResult(
            score=VerificationResult.clamp(combined),
            uncertainty=uncertainty,
            passed=passed,
            breakdown=breakdown,
            details={
                "dispersion": round(dispersion, 4),
                "members_errored": errored,
                "escalated": uncertainty > self._escalate,
            },
        )
