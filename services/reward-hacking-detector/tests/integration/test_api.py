"""HTTP API integration test (in-process ASGI, real Postgres + sandbox).

Exercises the public surface end to end with real API-key authentication:
  * launch an evaluation, poll until it completes;
  * read the exploit corpus and the report;
  * launch a second evaluation and compare the two;
  * confirm tenant isolation — another org's key cannot see the evaluation, and
    an unauthenticated request is rejected.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from touchstone_rhd.api.auth import Principal
from touchstone_rhd.app import create_app
from touchstone_rhd.config import Environment, Settings
from touchstone_rhd.knowledge.repository import KnowledgeBase, create_schema
from touchstone_rhd.orchestrator import Orchestrator
from touchstone_rhd.publisher import NullPublisher
from touchstone_rhd.worker import EvaluationJobRunner

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"

WEAK_CODE = (
    "def check(artifact):\n"
    "    ok = isinstance(artifact, dict) and 'answer' in artifact\n"
    "    return {'score': 1.0 if ok else 0.0}\n"
)


# Maps a tsk_ token to its org, standing in for the control-plane's introspection
# endpoint. RHD validates keys via introspection (faked here), so the tests need
# no control-plane tables at all — proving RHD runs on a fully isolated database.
_KEY_REGISTRY: dict[str, uuid.UUID] = {}


class _FakeIntrospector:
    async def introspect(self, api_key: str) -> Principal | None:
        org = _KEY_REGISTRY.get(api_key)
        if org is None:
            return None
        return Principal(organization_id=org, key_id="ci-key")


async def _seed(engine) -> dict:
    ids = {k: uuid.uuid4() for k in ("org", "ws", "proj", "verifier")}
    key_id, secret = secrets.token_hex(8), secrets.token_urlsafe(32)
    token = f"tsk_{key_id}_{secret}"
    await create_schema(engine)
    # The verifier under evaluation lives in RHD's own replica (fed in production
    # by the control-plane's `verifier.registered` event). No control-plane tables
    # are touched: auth goes through introspection, verifier data through the
    # replica.
    await KnowledgeBase(engine).upsert_verifier_ref(
        verifier_id=ids["verifier"], organization_id=ids["org"], version=1,
        verifier_type="code", definition={"code": WEAK_CODE, "threshold": 1.0})
    _KEY_REGISTRY[token] = ids["org"]
    ids["token"] = token
    return ids


@pytest_asyncio.fixture
async def client_and_ids():
    engine = create_async_engine(DB_URL)
    ids = await _seed(engine)
    app = create_app(Settings(environment=Environment.CI))
    # Wire state directly (bypass lifespan) so background tasks share this engine.
    app.state.engine = engine
    app.state.introspector = _FakeIntrospector()
    app.state.kb = KnowledgeBase(engine)
    app.state.runner = EvaluationJobRunner(
        kb=app.state.kb, orchestrator=Orchestrator(), publisher=NullPublisher(),
        max_retries=1, retry_backoff_s=0.01,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, ids, engine
    await engine.dispose()


async def _poll(client, headers, eval_id, *, timeout=30.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/v1/robustness/evaluations/{eval_id}", headers=headers)
        body = r.json()
        if body["status"] in ("completed", "failed"):
            return body
        await asyncio.sleep(0.25)
    raise AssertionError("evaluation did not finish in time")


@pytest.mark.asyncio
async def test_launch_poll_corpus_report_and_compare(client_and_ids):
    client, ids, _engine = client_and_ids
    headers = {"Authorization": f"Bearer {ids['token']}"}
    body = {"verifier_id": str(ids["verifier"]),
            "seed_cases": [{"artifact": {"answer": 42}, "should_pass": True},
                           {"artifact": {"answer": 0}, "should_pass": False}],
            "seed": 11, "max_attacks": 40}

    r = await client.post("/v1/robustness/evaluations", json=body, headers=headers)
    assert r.status_code == 202
    eval_id = r.json()["evaluation_id"]

    done = await _poll(client, headers, eval_id)
    assert done["status"] == "completed"
    assert done["exploits_found"] > 0
    assert done["robustness_score"] is not None

    # Exploit corpus.
    corpus = (await client.get(
        f"/v1/robustness/verifiers/{ids['verifier']}/exploits", headers=headers)).json()
    assert len(corpus) == done["exploits_found"]
    assert all("signature" in e and "category" in e for e in corpus)

    # Reproducible report.
    report = (await client.get(
        f"/v1/robustness/evaluations/{eval_id}/report", headers=headers)).json()
    assert report["seed"] == 11
    assert report["category_counts"]

    # Second evaluation + compare.
    r2 = await client.post("/v1/robustness/evaluations", json=body, headers=headers)
    eval_id2 = r2.json()["evaluation_id"]
    await _poll(client, headers, eval_id2)
    cmp = (await client.post("/v1/robustness/compare", headers=headers, json={
        "baseline_evaluation_id": eval_id, "candidate_evaluation_id": eval_id2,
    })).json()
    # Identical config => no regression.
    assert cmp["is_regression"] is False
    assert "delta" in cmp


@pytest.mark.asyncio
async def test_search_endpoint(client_and_ids):
    client, ids, _engine = client_and_ids
    headers = {"Authorization": f"Bearer {ids['token']}"}
    body = {"verifier_id": str(ids["verifier"]),
            "seed_cases": [{"artifact": {"answer": 42}, "should_pass": True},
                           {"artifact": {"answer": 0}, "should_pass": False}],
            "seed": 3, "max_attacks": 40}
    eval_id = (await client.post(
        "/v1/robustness/evaluations", json=body, headers=headers)).json()["evaluation_id"]
    await _poll(client, headers, eval_id)

    # Unfiltered search returns the corpus with version + failure-reason fields.
    allr = (await client.get("/v1/robustness/exploits/search", headers=headers)).json()
    assert allr
    assert all("failure_reason" in e and "verifier_version" in e for e in allr)

    # Filter by severity returns a consistent subset.
    sev = allr[0]["severity"]
    filtered = (await client.get(
        f"/v1/robustness/exploits/search?severity={sev}", headers=headers)).json()
    assert filtered and all(e["severity"] == sev for e in filtered)

    # Search requires auth.
    assert (await client.get("/v1/robustness/exploits/search")).status_code == 401


@pytest.mark.asyncio
async def test_accepts_control_plane_jwt(client_and_ids):
    """The RHD also accepts the user JWT the control-plane issues (the dashboard's
    credential), scoped to the org in the token's claim."""
    import datetime as _dt

    import jwt as _jwt

    from touchstone_rhd.config import get_settings

    client, ids, _engine = client_and_ids
    secret = get_settings().jwt_secret
    token = _jwt.encode(
        {"sub": str(uuid.uuid4()), "org": str(ids["org"]), "type": "access",
         "exp": _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=1)},
        secret, algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    # An org-scoped search authenticates and returns (possibly empty) results.
    r = await client.get("/v1/robustness/exploits/search", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # A token for a different org cannot see this org's verifier evaluations.
    other = _jwt.encode(
        {"sub": "x", "org": str(uuid.uuid4()), "type": "access",
         "exp": _dt.datetime.now(_dt.UTC) + _dt.timedelta(hours=1)},
        secret, algorithm="HS256",
    )
    r2 = await client.get(f"/v1/robustness/verifiers/{ids['verifier']}/trend",
                          headers={"Authorization": f"Bearer {other}"})
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_requires_authentication(client_and_ids):
    client, ids, _engine = client_and_ids
    r = await client.get(f"/v1/robustness/evaluations/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_tenant_isolation(client_and_ids):
    client, ids, _engine = client_and_ids
    headers = {"Authorization": f"Bearer {ids['token']}"}
    body = {"verifier_id": str(ids["verifier"]),
            "seed_cases": [{"artifact": {"answer": 42}, "should_pass": True}],
            "seed": 1, "max_attacks": 20}
    eval_id = (await client.post(
        "/v1/robustness/evaluations", json=body, headers=headers)).json()["evaluation_id"]
    await _poll(client, headers, eval_id)

    # A different org's key must not see this evaluation.
    other = await _seed(_engine)
    other_headers = {"Authorization": f"Bearer {other['token']}"}
    r = await client.get(f"/v1/robustness/evaluations/{eval_id}", headers=other_headers)
    assert r.status_code == 404
