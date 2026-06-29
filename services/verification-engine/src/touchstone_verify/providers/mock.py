"""Deterministic provider for tests/CI — no network, reproducible.

It returns a JSON judgment whose score is a stable hash of the prompt, so tests
are deterministic, plus honors an embedded ``__force_score__`` directive so
tests can assert specific behaviors.
"""

from __future__ import annotations

import hashlib
import json
import re

from .base import JudgeRequest, JudgeResponse


class MockProvider:
    async def complete(self, req: JudgeRequest) -> JudgeResponse:
        forced = re.search(r"__force_score__\s*=\s*([01](?:\.\d+)?)", req.prompt)
        if forced:
            score = float(forced.group(1))
        else:
            digest = hashlib.sha256(req.prompt.encode()).digest()
            score = round(digest[0] / 255, 3)
        body = json.dumps(
            {"score": score, "passed": score >= 0.5, "reasoning": "mock judgment"}
        )
        return JudgeResponse(text=body, model="mock-judge-1")
