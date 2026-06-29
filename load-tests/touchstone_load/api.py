"""Thin helpers that drive the real Touchstone API from a Locust client.

These build the exact request payloads the services expect (no placeholders) and
group requests under stable names so the statistics read cleanly. Each helper
takes a Locust ``client`` (a requests-style session that records metrics) so the
bootstrap traffic is measured alongside the steady-state load.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# An executable "code" verifier: deterministic, fast, and safe to run at scale.
# Matches the verification-engine's code-verifier contract (def check(artifact)
# returning {"score": ...}).
CODE_VERIFIER_DEFINITION = {
    "type": "code",
    "code": "def check(artifact):\n    return {'score': 1.0 if artifact == 42 else 0.0}",
    "threshold": 1.0,
}


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class TenantContext:
    """Everything a virtual user needs after bootstrapping a fresh tenant."""

    jwt: str
    org_id: str
    workspace_id: str
    project_id: str
    verifier_id: str
    api_key: str | None
    creds: dict[str, str]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def signup(client) -> tuple[str, str, dict[str, str]]:
    """Create a brand-new tenant; return (jwt, org_id, login_creds)."""
    suffix = _uid()
    creds = {
        "email": f"load-{suffix}@loadtest.io",
        "password": "load-test-password-123",
        "org_slug": f"load-{suffix}",
    }
    body = {
        "email": creds["email"],
        "password": creds["password"],
        "full_name": "Load Test",
        "org_name": f"Load {suffix}",
        "org_slug": creds["org_slug"],
    }
    with client.post("/v1/auth/signup", json=body, name="auth:signup",
                     catch_response=True) as resp:
        if resp.status_code != 201:
            resp.failure(f"signup -> {resp.status_code}")
            return "", "", creds
        data = resp.json()
        return data["access_token"], data["org_id"], creds


def login(client, creds: dict[str, str]) -> str:
    """Re-authenticate an existing user; return a fresh JWT."""
    body = {
        "email": creds["email"],
        "password": creds["password"],
        "org_slug": creds["org_slug"],
    }
    with client.post("/v1/auth/login", json=body, name="auth:login",
                     catch_response=True) as resp:
        if resp.status_code != 200:
            resp.failure(f"login -> {resp.status_code}")
            return ""
        return resp.json()["access_token"]


def create_workspace(client, jwt: str) -> str:
    suffix = _uid()
    body = {"name": f"ws-{suffix}", "slug": f"ws-{suffix}"}
    with client.post("/v1/workspaces", json=body, headers=_bearer(jwt),
                     name="workspace:create", catch_response=True) as resp:
        if resp.status_code != 201:
            resp.failure(f"workspace create -> {resp.status_code}")
            return ""
        return resp.json()["id"]


def create_project(client, jwt: str, workspace_id: str) -> str:
    suffix = _uid()
    body = {"name": f"proj-{suffix}", "slug": f"proj-{suffix}"}
    with client.post(f"/v1/workspaces/{workspace_id}/projects", json=body,
                     headers=_bearer(jwt), name="project:create",
                     catch_response=True) as resp:
        if resp.status_code != 201:
            resp.failure(f"project create -> {resp.status_code}")
            return ""
        return resp.json()["id"]


def register_verifier(client, jwt: str, project_id: str) -> str:
    suffix = _uid()
    body = {
        "name": f"verifier-{suffix}",
        "slug": f"verifier-{suffix}",
        "verifier_type": "code",
        "definition": CODE_VERIFIER_DEFINITION,
    }
    with client.post(f"/v1/projects/{project_id}/verifiers", json=body,
                     headers=_bearer(jwt), name="verifier:register",
                     catch_response=True) as resp:
        if resp.status_code not in (200, 201):
            resp.failure(f"verifier register -> {resp.status_code}")
            return ""
        return resp.json()["id"]


def create_api_key(client, jwt: str, project_id: str) -> str | None:
    body = {"name": f"key-{_uid()}", "role": "service", "project_id": project_id}
    with client.post("/v1/api-keys", json=body, headers=_bearer(jwt),
                     name="api_key:create", catch_response=True) as resp:
        if resp.status_code not in (200, 201):
            resp.failure(f"api key create -> {resp.status_code}")
            return None
        return resp.json().get("secret")


def bootstrap_tenant(client, *, with_api_key: bool = True) -> TenantContext | None:
    """Run the full signup -> workspace -> project -> verifier (-> key) chain."""
    jwt, org_id, creds = signup(client)
    if not jwt:
        return None
    workspace_id = create_workspace(client, jwt)
    if not workspace_id:
        return None
    project_id = create_project(client, jwt, workspace_id)
    if not project_id:
        return None
    verifier_id = register_verifier(client, jwt, project_id)
    if not verifier_id:
        return None
    api_key = create_api_key(client, jwt, project_id) if with_api_key else None
    return TenantContext(
        jwt=jwt, org_id=org_id, workspace_id=workspace_id,
        project_id=project_id, verifier_id=verifier_id, api_key=api_key, creds=creds,
    )


def submit_verification(client, jwt: str, verifier_id: str, artifact_ref: str) -> str | None:
    """Submit a verification run; return its id (202 Accepted)."""
    body = {"verifier_id": verifier_id, "artifact_ref": artifact_ref}
    with client.post("/v1/verifications", json=body, headers=_bearer(jwt),
                     name="verification:submit", catch_response=True) as resp:
        if resp.status_code != 202:
            resp.failure(f"submit -> {resp.status_code}")
            return None
        return resp.json()["id"]


def get_verification(client, jwt: str, verification_id: str):
    """Poll a single verification run; returns (status, response) or (None, resp)."""
    with client.get(f"/v1/verifications/{verification_id}", headers=_bearer(jwt),
                    name="verification:poll", catch_response=True) as resp:
        if resp.status_code != 200:
            resp.failure(f"poll -> {resp.status_code}")
            return None, resp
        return resp.json().get("status"), resp
