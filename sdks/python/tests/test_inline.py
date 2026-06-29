"""InlineGuard middleware tests using a mocked IVP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from touchstone import Blocked, InlineGuard, TouchstoneClient


def _decision(action: str, **extra) -> dict:
    base = {
        "decision_id": "00000000-0000-0000-0000-000000000001",
        "action": action, "risk_score": 0.1, "risk_band": "low",
        "reasons": {}, "latency_ms": 1.0, "content_sha256": "abc", "mode": "enforce",
        "redacted_content": None, "escalation": None, "degraded": False,
    }
    base.update(extra)
    return base


def _guard(handler) -> InlineGuard:
    return InlineGuard("http://ivp", api_key="tsk_a_b",
                       transport=httpx.MockTransport(handler))


def test_enforce_allow_returns_content():
    def handler(request):
        return httpx.Response(200, json=_decision("allow"))
    with _guard(handler) as g:
        assert g.enforce("hello", policy_slug="p") == "hello"


def test_enforce_redact_returns_redacted():
    def handler(request):
        return httpx.Response(200, json=_decision(
            "redact", risk_score=0.6, risk_band="high", redacted_content="he[REDACTED]"))
    with _guard(handler) as g:
        assert g.enforce("hello", policy_slug="p") == "he[REDACTED]"


def test_enforce_block_raises():
    def handler(request):
        return httpx.Response(200, json=_decision(
            "block", risk_score=0.95, risk_band="critical"))
    with _guard(handler) as g:
        with pytest.raises(Blocked) as exc:
            g.enforce("hello", policy_slug="p")
        assert exc.value.decision.action == "block"


def test_enforce_escalate_invokes_callback_and_passes_through():
    seen = []

    def handler(request):
        return httpx.Response(200, json=_decision("escalate", escalation={"verifier_ids": []}))
    with _guard(handler) as g:
        out = g.enforce("hello", policy_slug="p", on_escalate=seen.append)
    assert out == "hello"
    assert len(seen) == 1


def test_check_sends_auth_and_body():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_decision("allow"))
    with _guard(handler) as g:
        g.check("payload", policy_slug="prod", latency_budget_ms=50)
    assert captured["auth"] == "Bearer tsk_a_b"
    assert captured["body"]["content"] == "payload"
    assert captured["body"]["policy_slug"] == "prod"
    assert captured["body"]["latency_budget_ms"] == 50


def test_stream_returns_verdicts():
    def handler(request):
        return httpx.Response(200, json=[
            {"seq": 0, "action": "allow", "terminal": False, "decision": _decision("allow")},
            {"seq": 1, "action": "block", "terminal": True,
             "decision": _decision("block", risk_score=0.9, risk_band="critical")},
        ])
    with _guard(handler) as g:
        verdicts = g.stream(["a", "b"], policy_slug="p")
    assert verdicts[-1].terminal is True
    assert verdicts[-1].action == "block"


def test_client_inline_factory_shares_credentials():
    client = TouchstoneClient(api_key="tsk_shared")
    guard = client.inline("http://ivp", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json=_decision("allow"))))
    assert guard._api_key == "tsk_shared"
    assert guard.enforce("x", policy_slug="p") == "x"
