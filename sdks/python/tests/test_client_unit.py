"""SDK unit tests using httpx MockTransport — no server required.

These assert the client's wire behavior in isolation: correct method/path/body,
auth header injection, problem+json error mapping, response model parsing, and
the wait_for_verification polling state machine.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from touchstone import (
    ConflictError,
    NotFoundError,
    RateLimitError,
    TouchstoneClient,
    VerificationStatus,
)

NOW = "2026-06-28T00:00:00Z"


def make_client(handler, **kw) -> TouchstoneClient:
    return TouchstoneClient(
        "http://test", transport=httpx.MockTransport(handler), **kw
    )


def test_signup_parses_token_and_sets_auth():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={
            "access_token": "jwt-abc", "token_type": "Bearer", "expires_in": 3600,
            "org_id": str(uuid.uuid4()), "org_slug": "acme",
        })

    client = make_client(handler)
    pair = client.signup(email="a@b.com", password="x" * 9, org_name="Acme", org_slug="acme")
    assert pair.access_token == "jwt-abc"
    assert captured["path"] == "/v1/auth/signup"
    assert "a@b.com" in captured["body"]
    # The token is now stored and sent on subsequent calls.
    assert client._auth_header()["Authorization"] == "Bearer jwt-abc"


def test_api_key_takes_precedence_over_token():
    client = make_client(lambda r: httpx.Response(200, json=[]), api_key="tsk_key", token="jwt")
    assert client._auth_header()["Authorization"] == "Bearer tsk_key"


def test_auth_header_sent_on_requests():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=[])

    make_client(handler, api_key="tsk_xyz").list_api_keys()
    assert seen["auth"] == "Bearer tsk_xyz"


def test_register_verifier_builds_request_and_parses():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={
            "id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
            "name": "V", "slug": "v", "version": 1, "verifier_type": "code",
            "definition": {"code": "..."}, "robustness_score": None,
            "is_active": True, "created_at": NOW,
        })

    client = make_client(handler, api_key="tsk")
    pid = uuid.uuid4()
    v = client.register_verifier(pid, "V", "v", "code", {"code": "..."})
    assert v.version == 1 and v.verifier_type.value == "code"
    assert captured["path"] == f"/v1/projects/{pid}/verifiers"
    assert "code" in captured["body"]


def test_submit_verification_parses_pending():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={
            "id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
            "verifier_id": str(uuid.uuid4()), "status": "pending",
            "score": None, "uncertainty": None, "passed": None,
            "risk_score": None, "grader_breakdown": {}, "latency_ms": None,
            "created_at": NOW,
        })

    run = make_client(handler, api_key="tsk").submit_verification(uuid.uuid4(), "s3://x")
    assert run.status == VerificationStatus.PENDING


@pytest.mark.parametrize("status,exc", [
    (404, NotFoundError), (409, ConflictError), (429, RateLimitError),
])
def test_error_mapping(status, exc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"type": "https://errors.touchstone.ai/x", "title": "T",
                  "detail": "boom", "status": status},
            headers={"Retry-After": "5"} if status == 429 else {},
        )

    client = make_client(handler, api_key="tsk")
    with pytest.raises(exc) as ei:
        client.get_verification(uuid.uuid4())
    assert ei.value.detail == "boom"
    assert ei.value.status == status
    if status == 429:
        assert ei.value.retry_after == 5


def test_wait_for_verification_polls_until_terminal():
    calls = {"n": 0}
    rid = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        status = "completed" if calls["n"] >= 3 else "running"
        body = {
            "id": rid, "project_id": str(uuid.uuid4()),
            "verifier_id": str(uuid.uuid4()), "status": status,
            "score": 1.0 if status == "completed" else None,
            "uncertainty": 0.0 if status == "completed" else None,
            "passed": True if status == "completed" else None,
            "risk_score": None, "grader_breakdown": {}, "latency_ms": 12,
            "created_at": NOW,
        }
        return httpx.Response(200, json=body)

    client = make_client(handler, api_key="tsk")
    result = client.wait_for_verification(rid, timeout=5, interval=0.01)
    assert result.status == VerificationStatus.COMPLETED
    assert result.score == 1.0 and result.passed is True
    assert calls["n"] == 3  # polled until terminal


def test_wait_for_verification_times_out():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": str(uuid.uuid4()), "project_id": str(uuid.uuid4()),
            "verifier_id": str(uuid.uuid4()), "status": "running",
            "grader_breakdown": {}, "created_at": NOW,
        })

    client = make_client(handler, api_key="tsk")
    with pytest.raises(TimeoutError):
        client.wait_for_verification(uuid.uuid4(), timeout=0.05, interval=0.01)
