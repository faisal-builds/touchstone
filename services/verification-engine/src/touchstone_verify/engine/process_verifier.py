"""Process verifier — step-level supervision of a trajectory.

For long-horizon agentic tasks the final outcome is often ambiguous, so we grade
the *process*: each step of the trajectory is scored, and the verifier reports
the aggregate plus the index of the first failing step (where the agent went
wrong), which is far more useful for training signal than a single end reward.

Definition schema::

    {
        "type": "process",
        "step_code": "def check_step(step, index):\n    return {'score': ...}",
        "aggregation": "mean" | "min" | "product",
        "threshold": 0.8
    }

The artifact must be a list of steps. Each step is graded by ``check_step`` in
the sandbox (untrusted), exactly like the code verifier.
"""

from __future__ import annotations

import math
from typing import Any

from ..sandbox.runner import SandboxRunner, sanitize_definition_limits
from .base import (
    VerificationResult,
    Verifier,
    VerifierContext,
    VerifierError,
    VerifierFamily,
)

_AGG = {
    "mean": lambda xs: sum(xs) / len(xs),
    "min": min,
    "product": lambda xs: math.prod(xs),
}


class ProcessVerifier(Verifier):
    family = VerifierFamily.PROCESS

    def __init__(self, definition: dict[str, Any], runner: SandboxRunner | None = None):
        step_code = definition.get("step_code")
        if not isinstance(step_code, str) or not step_code.strip():
            raise VerifierError("process verifier requires 'step_code'")
        self._agg = definition.get("aggregation", "mean")
        if self._agg not in _AGG:
            raise VerifierError(f"unknown aggregation: {self._agg}")
        self._threshold = float(definition.get("threshold", 0.8))
        # See CodeVerifier: customer-authored limits can only narrow the sandbox,
        # and are validated even when a shared runner is injected (M3).
        try:
            limits = sanitize_definition_limits(definition.get("limits"))
        except ValueError as exc:
            raise VerifierError(str(exc)) from exc
        self._runner = runner or SandboxRunner(limits)
        # Wrap the per-step grader so the sandbox harness sees a check(artifact)
        # where artifact == {"step": <step>, "index": <i>}.
        self._wrapped = (
            step_code
            + "\n\ndef check(artifact):\n"
            "    return check_step(artifact['step'], artifact['index'])\n"
        )

    async def verify(self, artifact: Any, ctx: VerifierContext) -> VerificationResult:
        if not isinstance(artifact, list) or not artifact:
            raise VerifierError("process verifier expects a non-empty list of steps")

        step_scores: list[float] = []
        first_failure: int | None = None
        for i, step in enumerate(artifact):
            outcome = await self._runner.run(self._wrapped, {"step": step, "index": i})
            if not outcome.ok:
                raise VerifierError(f"step {i} sandbox failed: {outcome.error}")
            s = VerificationResult.clamp(float((outcome.result or {}).get("score", 0.0)))
            step_scores.append(s)
            if first_failure is None and s < 1.0:
                first_failure = i

        score = VerificationResult.clamp(_AGG[self._agg](step_scores))
        return VerificationResult(
            score=score,
            uncertainty=0.0,
            passed=score >= self._threshold,
            breakdown={f"step_{i}": s for i, s in enumerate(step_scores)},
            details={"first_failure_index": first_failure, "n_steps": len(step_scores)},
        )
