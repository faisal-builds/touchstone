"""Model provider abstraction for the model (LLM-as-judge) verifier.

The judge needs to call *some* model to score an artifact against a rubric. We
abstract the provider so the judge logic is provider-agnostic and so CI can run
fully offline against a deterministic ``MockProvider``. A real
``AnthropicProvider`` (httpx) is included and used when an API key is present.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol


@dataclasses.dataclass(frozen=True, slots=True)
class JudgeRequest:
    system: str
    prompt: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclasses.dataclass(frozen=True, slots=True)
class JudgeResponse:
    text: str
    model: str


class ModelProvider(Protocol):
    async def complete(self, req: JudgeRequest) -> JudgeResponse:
        ...
