"""Model verifier — LLM-as-judge for fuzzy, non-deterministically-checkable work.

Definition schema::

    {
        "type": "model",
        "model": "claude-3-5-sonnet-latest",
        "rubric": "Score 1.0 if the answer is correct and complete, else lower.",
        "threshold": 0.5,
        "samples": 3        # optional self-consistency samples (default 1)
    }

The judge is prompted to return STRICT JSON ``{"score", "passed", "reasoning"}``.
When ``samples > 1`` we sample repeatedly and use the mean as the score and the
spread as uncertainty — a cheap self-consistency signal that is the first line
of defense against a single hallucinated judgment.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Any

from ..providers.base import JudgeRequest, ModelProvider
from .base import (
    VerificationResult,
    Verifier,
    VerifierContext,
    VerifierError,
    VerifierFamily,
)

_SYSTEM = (
    "You are an impartial verification judge. You are given an artifact and a "
    "rubric. Respond with STRICT JSON and nothing else: "
    '{"score": <float 0..1>, "passed": <bool>, "reasoning": <short string>}.'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class ModelVerifier(Verifier):
    family = VerifierFamily.MODEL

    def __init__(self, definition: dict[str, Any], provider: ModelProvider):
        rubric = definition.get("rubric")
        if not isinstance(rubric, str) or not rubric.strip():
            raise VerifierError("model verifier requires a 'rubric' string")
        self._rubric = rubric
        self._model = definition.get("model", "claude-3-5-sonnet-latest")
        self._threshold = float(definition.get("threshold", 0.5))
        self._samples = max(1, int(definition.get("samples", 1)))
        self._provider = provider

    def _prompt(self, artifact: Any) -> str:
        artifact_str = (
            artifact if isinstance(artifact, str) else json.dumps(artifact, default=str)
        )
        return (
            f"# Rubric\n{self._rubric}\n\n"
            f"# Artifact under test\n{artifact_str}\n\n"
            "Return only the JSON object."
        )

    @staticmethod
    def _parse_score(text: str) -> float:
        match = _JSON_RE.search(text)
        if not match:
            raise VerifierError("judge returned no JSON")
        try:
            obj = json.loads(match.group(0))
            return VerificationResult.clamp(float(obj["score"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise VerifierError(f"unparseable judge response: {exc}") from exc

    async def verify(self, artifact: Any, ctx: VerifierContext) -> VerificationResult:
        prompt = self._prompt(artifact)
        scores: list[float] = []
        for _ in range(self._samples):
            resp = await self._provider.complete(
                JudgeRequest(system=_SYSTEM, prompt=prompt, model=self._model,
                             temperature=0.0 if self._samples == 1 else 0.7)
            )
            scores.append(self._parse_score(resp.text))

        score = statistics.fmean(scores)
        # Uncertainty from sample disagreement: stdev of samples, scaled.
        uncertainty = 0.0
        if len(scores) > 1:
            uncertainty = VerificationResult.clamp(statistics.pstdev(scores) * 2)
        return VerificationResult(
            score=VerificationResult.clamp(score),
            uncertainty=uncertainty,
            passed=score >= self._threshold,
            breakdown={"model": score},
            details={"samples": scores, "model": self._model},
        )
