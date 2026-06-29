"""Synchronous Touchstone API client.

Usage::

    from touchstone import TouchstoneClient

    client = TouchstoneClient("http://localhost:8000")
    client.signup(email="me@acme.com", password="...", org_name="Acme",
                  org_slug="acme")            # stores the JWT on the client
    key = client.create_api_key("ci", role="member")
    ws = client.create_workspace("Research", "research")
    project = client.create_project(ws.id, "Coding Agent", "coding-agent")
    verifier = client.register_verifier(
        project.id, "Answer Check", "answer-check", "code",
        {"code": "def check(a):\\n return {'score': 1.0 if a['x']==42 else 0.0}"},
    )
    run = client.submit_verification(verifier.id, "s3://bucket/output.json")
    result = client.wait_for_verification(run.id)
    print(result.score, result.passed)

Auth precedence: an explicit API key (``api_key=`` or ``set_api_key``) is used if
present, otherwise the JWT obtained from ``signup``/``login``. Both are sent as
``Authorization: Bearer``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from . import _version
from .errors import error_for_status
from .models import (
    ApiKey,
    ApiKeyCreated,
    Project,
    TokenPair,
    Verification,
    Verifier,
    Workspace,
)

_DEFAULT_TIMEOUT = 30.0


class TouchstoneClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._token = token
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": f"touchstone-python/{_version.__version__}"},
        )

    # --- lifecycle ------------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> TouchstoneClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- credentials ----------------------------------------------------------
    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key

    def set_token(self, token: str) -> None:
        self._token = token

    def inline(self, base_url: str = "http://localhost:8050", **kw: Any):
        """Return an :class:`InlineGuard` for the IVP sharing these credentials."""
        from .inline import InlineGuard
        return InlineGuard(base_url, api_key=self._api_key, token=self._token, **kw)

    def _auth_header(self) -> dict[str, str]:
        cred = self._api_key or self._token
        return {"Authorization": f"Bearer {cred}"} if cred else {}

    # --- transport ------------------------------------------------------------
    def _request(self, method: str, path: str, *, json: Any | None = None) -> Any:
        resp = self._http.request(method, path, json=json, headers=self._auth_header())
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"detail": resp.text}
            retry_after = resp.headers.get("Retry-After")
            raise error_for_status(
                resp.status_code, body,
                retry_after=int(retry_after) if retry_after else None,
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # --- auth -----------------------------------------------------------------
    def signup(
        self, *, email: str, password: str, org_name: str, org_slug: str,
        full_name: str | None = None,
    ) -> TokenPair:
        data = self._request("POST", "/v1/auth/signup", json={
            "email": email, "password": password, "org_name": org_name,
            "org_slug": org_slug, "full_name": full_name,
        })
        pair = TokenPair.model_validate(data)
        self._token = pair.access_token
        return pair

    def login(self, *, email: str, password: str, org_slug: str | None = None) -> TokenPair:
        data = self._request("POST", "/v1/auth/login", json={
            "email": email, "password": password, "org_slug": org_slug,
        })
        pair = TokenPair.model_validate(data)
        self._token = pair.access_token
        return pair

    # --- api keys -------------------------------------------------------------
    def create_api_key(
        self, name: str, *, role: str = "service",
        project_id: uuid.UUID | str | None = None,
    ) -> ApiKeyCreated:
        data = self._request("POST", "/v1/api-keys", json={
            "name": name, "role": role,
            "project_id": str(project_id) if project_id else None,
        })
        return ApiKeyCreated.model_validate(data)

    def list_api_keys(self) -> list[ApiKey]:
        return [ApiKey.model_validate(x) for x in self._request("GET", "/v1/api-keys")]

    # --- workspaces / projects ------------------------------------------------
    def create_workspace(self, name: str, slug: str) -> Workspace:
        data = self._request("POST", "/v1/workspaces", json={"name": name, "slug": slug})
        return Workspace.model_validate(data)

    def create_project(
        self, workspace_id: uuid.UUID | str, name: str, slug: str,
        description: str | None = None,
    ) -> Project:
        data = self._request(
            "POST", f"/v1/workspaces/{workspace_id}/projects",
            json={"name": name, "slug": slug, "description": description},
        )
        return Project.model_validate(data)

    # --- verifiers ------------------------------------------------------------
    def register_verifier(
        self, project_id: uuid.UUID | str, name: str, slug: str,
        verifier_type: str, definition: dict,
    ) -> Verifier:
        data = self._request(
            "POST", f"/v1/projects/{project_id}/verifiers",
            json={"name": name, "slug": slug, "verifier_type": verifier_type,
                  "definition": definition},
        )
        return Verifier.model_validate(data)

    def list_verifiers(self, project_id: uuid.UUID | str) -> list[Verifier]:
        data = self._request("GET", f"/v1/projects/{project_id}/verifiers")
        return [Verifier.model_validate(x) for x in data]

    # --- verifications --------------------------------------------------------
    def submit_verification(
        self, verifier_id: uuid.UUID | str, artifact_ref: str,
        *, idempotency_key: str | None = None,
    ) -> Verification:
        data = self._request("POST", "/v1/verifications", json={
            "verifier_id": str(verifier_id), "artifact_ref": artifact_ref,
            "idempotency_key": idempotency_key,
        })
        return Verification.model_validate(data)

    def get_verification(self, verification_id: uuid.UUID | str) -> Verification:
        data = self._request("GET", f"/v1/verifications/{verification_id}")
        return Verification.model_validate(data)

    def wait_for_verification(
        self, verification_id: uuid.UUID | str, *,
        timeout: float = 60.0, interval: float = 0.5,
    ) -> Verification:
        """Poll until the run reaches a terminal state or ``timeout`` elapses."""
        deadline = time.monotonic() + timeout
        while True:
            run = self.get_verification(verification_id)
            if run.status.is_terminal:
                return run
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"verification {verification_id} still {run.status.value} "
                    f"after {timeout}s"
                )
            time.sleep(interval)
