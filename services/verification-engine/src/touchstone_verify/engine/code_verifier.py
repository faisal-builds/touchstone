"""Code verifier — deterministic grading via the sandbox.

Definition schema::

    {
        "type": "code",
        "code": "def check(artifact):\n    return {'score': 1.0 if ... else 0.0}",
        "threshold": 1.0      # optional; score >= threshold => passed
    }

Code verifiers are the gold standard when ground truth is checkable (tests pass,
output matches, invariant holds). They are deterministic, so their reported
``uncertainty`` is 0.0 on success. A sandbox execution failure raises
``VerifierError`` (FAILED), which is distinct from a legitimate low score.
"""

from __future__ import annotations

from typing import Any

from ..sandbox.runner import SandboxLimits, SandboxRunner
from .base import (
    VerificationResult,
    Verifier,
    VerifierContext,
    VerifierError,
    VerifierFamily,
)


class CodeVerifier(Verifier):
    family = VerifierFamily.CODE

    def __init__(self, definition: dict[str, Any], runner: SandboxRunner | None = None):
        code = definition.get("code")
        if not isinstance(code, str) or not code.strip():
            raise VerifierError("code verifier requires a non-empty 'code' string")
        self._code = code
        self._threshold = float(definition.get("threshold", 1.0))
        # Allow per-verifier sandbox tuning, else safe defaults.
        limits = definition.get("limits") or {}
        self._runner = runner or SandboxRunner(SandboxLimits(**limits))

    async def verify(self, artifact: Any, ctx: VerifierContext) -> VerificationResult:
        outcome = await self._runner.run(self._code, artifact)
        if not outcome.ok:
            raise VerifierError(outcome.error or "sandbox failed")
        result = outcome.result or {}
        score = VerificationResult.clamp(float(result.get("score", 0.0)))
        passed = bool(result.get("passed", score >= self._threshold))
        return VerificationResult(
            score=score,
            uncertainty=0.0,  # deterministic
            passed=passed,
            breakdown={"code": score},
            details={"sandbox": result.get("details", {})},
        )
