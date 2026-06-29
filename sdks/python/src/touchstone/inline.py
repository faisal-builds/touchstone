"""Inline guard — client middleware for the Touchstone Inline Verification Plane.

Wrap a model/agent output and enforce the plane's verdict in one call::

    guard = InlineGuard("http://localhost:8050", api_key="tsk_...")
    safe = guard.enforce(model_output, policy_slug="prod")   # -> text, or raises Blocked

Semantics:
  * **allow**     → the original content is returned;
  * **redact**    → the redacted content is returned;
  * **escalate**  → the content is returned (the deep verdict resolves async) and
                    ``on_escalate`` is invoked if supplied;
  * **block**     → :class:`Blocked` is raised.

For streamed generations, :meth:`stream` feeds chunks and stops early when the
plane blocks, so you can cut a bad generation mid-flight.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import httpx
from pydantic import BaseModel, Field

from ._version import __version__
from .errors import TouchstoneError, error_for_status


class Blocked(TouchstoneError):
    """Raised by :meth:`InlineGuard.enforce` when the plane blocks the content."""

    def __init__(self, decision: InlineDecision) -> None:
        super().__init__(f"inline plane blocked content (risk={decision.risk_score})",
                         status=200)
        self.decision = decision


class InlineDecision(BaseModel):
    decision_id: str
    action: str
    risk_score: float
    risk_band: str
    reasons: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    content_sha256: str
    mode: str = "enforce"
    redacted_content: str | None = None
    escalation: dict[str, Any] | None = None
    degraded: bool = False


class StreamVerdict(BaseModel):
    seq: int
    action: str
    terminal: bool
    decision: InlineDecision


class InlineGuard:
    def __init__(
        self, base_url: str = "http://localhost:8050", *,
        api_key: str | None = None, token: str | None = None, timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._token = token
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
            headers={"User-Agent": f"touchstone-python/{__version__}"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> InlineGuard:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _auth(self) -> dict[str, str]:
        cred = self._api_key or self._token
        return {"Authorization": f"Bearer {cred}"} if cred else {}

    def _post(self, path: str, body: dict) -> Any:
        resp = self._http.post(path, json=body, headers=self._auth())
        if resp.status_code >= 400:
            try:
                problem = resp.json()
            except ValueError:
                problem = {"detail": resp.text}
            raise error_for_status(resp.status_code, problem)
        return resp.json()

    def check(
        self, content: str, *, policy_slug: str | None = None, policy_id: str | None = None,
        latency_budget_ms: float | None = None, mode: str = "enforce",
        context: dict | None = None,
    ) -> InlineDecision:
        """Call the plane and return the raw decision (no enforcement)."""
        body = {
            "content": content, "policy_slug": policy_slug, "policy_id": policy_id,
            "latency_budget_ms": latency_budget_ms, "mode": mode,
            "context": context or {},
        }
        return InlineDecision.model_validate(self._post("/v1/inline/verify", body))

    def enforce(
        self, content: str, *, policy_slug: str | None = None, policy_id: str | None = None,
        latency_budget_ms: float | None = None,
        on_escalate: Callable[[InlineDecision], None] | None = None,
        context: dict | None = None,
    ) -> str:
        """Enforce the verdict: return safe text or raise :class:`Blocked`."""
        decision = self.check(
            content, policy_slug=policy_slug, policy_id=policy_id,
            latency_budget_ms=latency_budget_ms, context=context,
        )
        if decision.action == "block":
            raise Blocked(decision)
        if decision.action == "redact":
            return decision.redacted_content or ""
        if decision.action == "escalate" and on_escalate is not None:
            on_escalate(decision)
        return content

    def stream(
        self, chunks: Iterable[str], *, policy_slug: str | None = None,
        policy_id: str | None = None, latency_budget_ms: float | None = None,
        mode: str = "enforce",
    ) -> list[StreamVerdict]:
        """Stream-verify chunks; the plane early-exits on a terminal verdict."""
        body = {
            "chunks": list(chunks), "policy_slug": policy_slug, "policy_id": policy_id,
            "latency_budget_ms": latency_budget_ms, "mode": mode,
        }
        data = self._post("/v1/inline/verify/stream", body)
        return [StreamVerdict.model_validate(v) for v in data]
