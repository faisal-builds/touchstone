"""Attack execution engine.

Runs adversarial variants through the target verifier and records what the
verifier did. Key properties:

  * **Reuses the verification-engine** — the verifier is built by the engine's
    ``VerifierFactory`` and executed via its ``verify()`` contract, so code
    verifiers run inside the same hardened sandbox the platform already trusts.
    The detector never re-implements execution or sandboxing.
  * **Bounded parallelism** — variants run concurrently under a semaphore so
    thousands of attempts complete quickly without exhausting resources.
  * **Safety** — any verifier error/timeout/crash on adversarial input is caught
    and recorded as an ``errored`` outcome (never an exploit, never a process
    failure).
  * **Determinism** — outcomes are returned ordered by the variant ordinal,
    independent of completion order, so a replay with the same seed yields an
    identical outcome list.
"""

from __future__ import annotations

import asyncio

import structlog
from touchstone_verify.engine.base import Verifier, VerifierContext, VerifierError

from ..domain.models import AttackOutcome, AttackVariant

log = structlog.get_logger(__name__)


class AttackExecutor:
    def __init__(self, *, max_concurrency: int = 16, per_attack_timeout_s: float = 15.0):
        self._sem = asyncio.Semaphore(max_concurrency)
        self._timeout = per_attack_timeout_s

    async def execute(
        self, verifier: Verifier, variants: list[AttackVariant], *, evaluation_id: str
    ) -> list[AttackOutcome]:
        async def _one(variant: AttackVariant) -> AttackOutcome:
            async with self._sem:
                ctx = VerifierContext(
                    verification_id=f"{evaluation_id}:{variant.ordinal}",
                    verifier_id=evaluation_id,
                    timeout_s=self._timeout,
                )
                try:
                    result = await asyncio.wait_for(
                        verifier.verify(variant.artifact, ctx), timeout=self._timeout
                    )
                except (VerifierError, TimeoutError, Exception) as exc:  # noqa: BLE001
                    return AttackOutcome(
                        variant=variant, verifier_passed=False, verifier_score=0.0,
                        verifier_uncertainty=0.0, errored=True, error=str(exc)[:500],
                    )
                return AttackOutcome(
                    variant=variant,
                    verifier_passed=result.passed,
                    verifier_score=result.score,
                    verifier_uncertainty=result.uncertainty,
                    verifier_breakdown=dict(result.breakdown),
                    verifier_details=dict(result.details),
                )

        outcomes = await asyncio.gather(*(_one(v) for v in variants))
        # Deterministic order regardless of concurrency completion order.
        return sorted(outcomes, key=lambda o: o.variant.ordinal)
