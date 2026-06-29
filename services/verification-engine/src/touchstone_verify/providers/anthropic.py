"""Real Anthropic Messages API provider (httpx).

Used when TOUCHSTONE_VERIFY_ANTHROPIC_API_KEY is configured. The judge prompts
the model to respond with strict JSON; parsing/validation happens in the
model verifier, not here.
"""

from __future__ import annotations

import httpx

from .base import JudgeRequest, JudgeResponse

_API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider:
    def __init__(self, api_key: str, *, timeout_s: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout_s

    async def complete(self, req: JudgeRequest) -> JudgeResponse:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "system": req.system,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", [])
            if block.get("type") == "text"
        )
        return JudgeResponse(text=text, model=data.get("model", req.model))
