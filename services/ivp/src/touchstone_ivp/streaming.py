"""Streaming inline verification.

For token/chunk-streamed model output, the plane re-evaluates the accumulated
text as chunks arrive and **early-exits** the moment a terminal action
(block/redact) is reached — so a bad generation is stopped mid-stream rather than
after the whole response is produced. Allow/escalate are non-terminal: streaming
continues (escalation resolves asynchronously). The fast-tier cache makes the
repeated evaluation cheap when prefixes are stable.
"""

from __future__ import annotations

from .plane import InlinePlane, PlaneResult
from .schemas import Action, InlineVerifyRequest


class StreamSession:
    def __init__(self, plane: InlinePlane, org_id, *, policy_id=None, policy_slug=None,
                 latency_budget_ms=None, mode="enforce") -> None:
        self._plane = plane
        self._org_id = org_id
        self._policy_id = policy_id
        self._policy_slug = policy_slug
        self._budget = latency_budget_ms
        self._mode = mode
        self._buffer: list[str] = []
        self._closed = False

    @property
    def accumulated(self) -> str:
        return "".join(self._buffer)

    async def push(self, chunk: str) -> tuple[PlaneResult, bool]:
        """Feed a chunk; return (result, terminal).

        ``terminal`` is True when streaming should stop (the action is block or
        redact). Once terminal, further pushes raise.
        """
        if self._closed:
            raise RuntimeError("stream already terminated")
        self._buffer.append(chunk)
        req = InlineVerifyRequest(
            policy_id=self._policy_id, policy_slug=self._policy_slug,
            content=self.accumulated, latency_budget_ms=self._budget, mode=self._mode,
        )
        result = await self._plane.verify(self._org_id, req)
        terminal = result.decision.action in (Action.BLOCK, Action.REDACT)
        if terminal:
            self._closed = True
        return result, terminal
