"""SDK end-to-end integration test.

Boots the real control-plane app in a background uvicorn server against the live
Postgres, then drives the entire self-serve flow *through the SDK* (signup →
workspace → project → API key → register verifier → submit → fetch). This proves
the platform is callable end to end by a real client over real HTTP.

Skipped automatically if the control-plane package or Postgres is unavailable.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid

import httpx
import pytest

uvicorn = pytest.importorskip("uvicorn")
pytest.importorskip("touchstone_control")

from touchstone import TouchstoneClient, VerificationStatus  # noqa: E402
from touchstone_control.app import create_app  # noqa: E402
from touchstone_control.core.config import Environment, Settings  # noqa: E402

DB_URL = "postgresql+asyncpg://touchstone@127.0.0.1:5432/touchstone"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    settings = Settings(
        environment=Environment.CI,
        database_url=DB_URL,
        redis_url="redis://127.0.0.1:6379/0",
        jwt_secret="integration-secret-at-least-32-bytes-long!!",
    )
    try:
        app = create_app(settings)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cannot build app: {exc}")

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):  # wait up to ~5s for readiness
        try:
            if httpx.get(f"{base}/healthz", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    else:  # pragma: no cover
        srv.should_exit = True
        pytest.skip("server did not become healthy (is Postgres up?)")

    yield base
    srv.should_exit = True
    thread.join(timeout=5)


def test_full_self_serve_flow_via_sdk(server):
    sfx = uuid.uuid4().hex[:10]
    with TouchstoneClient(server) as client:
        # 1. Signup -> JWT stored on the client
        pair = client.signup(
            email=f"dev-{sfx}@example.com",
            password="correct horse battery staple",
            org_name=f"Acme {sfx}",
            org_slug=f"acme-{sfx}",
        )
        assert pair.access_token and pair.org_slug == f"acme-{sfx}"

        # 2. Mint an API key and switch the client to use it
        key = client.create_api_key("ci", role="member")
        assert key.secret.startswith("tsk_")
        client.set_api_key(key.secret)

        # 3. Workspace + project
        ws = client.create_workspace("Research", "research")
        project = client.create_project(ws.id, "Coding Agent", "coding-agent")
        assert project.workspace_id == ws.id

        # 4. Register a verifier (auto-versioned to 1)
        verifier = client.register_verifier(
            project.id, "Answer 42", "answer-42", "code",
            {"code": "def check(a):\n return {'score': 1.0 if a.get('answer')==42 else 0.0}",
             "threshold": 1.0},
        )
        assert verifier.version == 1

        # 5. Submit an artifact -> PENDING (engine processes asynchronously)
        run = client.submit_verification(verifier.id, artifact_ref="demo/run.json")
        assert run.status == VerificationStatus.PENDING

        # 6. Fetch it back through the SDK
        fetched = client.get_verification(run.id)
        assert fetched.id == run.id
        assert fetched.verifier_id == verifier.id


def test_login_via_sdk(server):
    sfx = uuid.uuid4().hex[:10]
    email = f"login-{sfx}@example.com"
    with TouchstoneClient(server) as c1:
        c1.signup(email=email, password="another good passphrase",
                  org_name=f"Beta {sfx}", org_slug=f"beta-{sfx}")
    with TouchstoneClient(server) as c2:
        pair = c2.login(email=email, password="another good passphrase")
        assert pair.org_slug == f"beta-{sfx}"
        # The token works for an authenticated call.
        assert c2.list_api_keys() == []
