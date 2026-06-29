"""Locust virtual users for the Touchstone load suite.

Three user types:

* ``ControlPlaneUser``      — the breadth scenarios (auth, registration, dashboard
  reads, audit) that exercise the control-plane API surface.
* ``VerificationHotPathUser`` — the focus: submit a verification and poll it to
  completion, recording submission throughput, poll latency, end-to-end
  completion time, and the timeout rate.
* ``RobustnessUser``        — reward-hacking-detector scenarios (evaluation submit,
  poll, exploit search). Opt-in (needs the RHD running and the verifier-replica
  event flow), so it is only attached when ``TOUCHSTONE_LOAD_ENABLE_RHD`` is set.
"""

from __future__ import annotations

import time

import requests
from locust import HttpUser, between, task

from . import api, metrics
from .config import get_profile, get_targets

_PROFILE = get_profile()
_TARGETS = get_targets()


class ControlPlaneUser(HttpUser):
    """Breadth coverage of the control-plane API + dashboard read paths."""

    weight = 2
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.ctx = api.bootstrap_tenant(self.client)

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.ctx.jwt}"} if self.ctx else {}

    @task(4)
    def dashboard_reads(self) -> None:
        if not self.ctx:
            return
        h = self._auth
        self.client.get("/v1/workspaces", headers=h, name="dashboard:workspaces")
        self.client.get(
            f"/v1/workspaces/{self.ctx.workspace_id}/projects",
            headers=h, name="dashboard:projects",
        )
        self.client.get(
            f"/v1/projects/{self.ctx.project_id}/verifiers",
            headers=h, name="dashboard:verifiers",
        )
        self.client.get("/v1/verifications", headers=h, name="dashboard:verifications")

    @task(2)
    def audit_read(self) -> None:
        if not self.ctx:
            return
        self.client.get("/v1/audit", headers=self._auth, name="audit:list")

    @task(1)
    def register_more(self) -> None:
        if not self.ctx:
            return
        api.register_verifier(self.client, self.ctx.jwt, self.ctx.project_id)

    @task(1)
    def rotate_key(self) -> None:
        if not self.ctx:
            return
        api.create_api_key(self.client, self.ctx.jwt, self.ctx.project_id)

    @task(1)
    def re_login(self) -> None:
        if not self.ctx:
            return
        fresh = api.login(self.client, self.ctx.creds)
        if fresh:
            self.ctx.jwt = fresh


class VerificationHotPathUser(HttpUser):
    """The verification hot path: submit, then poll to completion."""

    weight = 3
    wait_time = between(0.1, 0.6)

    def on_start(self) -> None:
        self.ctx = api.bootstrap_tenant(self.client, with_api_key=False)

    @task
    def submit_and_poll(self) -> None:
        if not self.ctx:
            return
        verification_id = api.submit_verification(
            self.client, self.ctx.jwt, self.ctx.verifier_id, _TARGETS.artifact_ref
        )
        if not verification_id:
            return
        metrics.record_submitted()

        deadline = time.monotonic() + _PROFILE.poll_timeout_s
        started = time.monotonic()
        while time.monotonic() < deadline:
            status, _ = api.get_verification(self.client, self.ctx.jwt, verification_id)
            if status in ("completed", "failed"):
                metrics.record_completion(
                    self.environment, (time.monotonic() - started) * 1000.0
                )
                return
            time.sleep(_PROFILE.poll_interval_s)

        # No terminal state within the budget. When a worker is expected this is a
        # real timeout; otherwise (CI/local, no worker) it is simply not counted
        # against the run via the profile's thresholds.
        metrics.record_timeout(self.environment)


class RobustnessUser(HttpUser):
    """Reward-hacking-detector scenarios. Opt-in; targets the RHD host."""

    weight = 1
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        # Bootstrap a tenant + key on the control-plane out-of-band (the measured
        # host for this user is the RHD). The verifier must already be replicated
        # into the RHD via the verifier.registered event (present in staging/AWS).
        self.ctx = None
        try:
            session = requests.Session()
            base = _TARGETS.control_plane_url
            ctx = api.bootstrap_tenant(_PrefixedSession(session, base))
        except requests.RequestException:
            return
        self.ctx = ctx

    def _key_auth(self) -> dict[str, str]:
        if self.ctx and self.ctx.api_key:
            return {"Authorization": f"Bearer {self.ctx.api_key}"}
        return {}

    @task(3)
    def evaluation_submit_and_poll(self) -> None:
        if not self.ctx:
            return
        body = {"verifier_id": self.ctx.verifier_id, "seed": 1337, "max_attacks": 64}
        with self.client.post("/v1/robustness/evaluations", json=body,
                              headers=self._key_auth(), name="robustness:submit",
                              catch_response=True) as resp:
            if resp.status_code not in (200, 202):
                resp.failure(f"rhd submit -> {resp.status_code}")
                return
            eval_id = resp.json().get("evaluation_id")
        if not eval_id:
            return
        deadline = time.monotonic() + _PROFILE.poll_timeout_s
        while time.monotonic() < deadline:
            with self.client.get(f"/v1/robustness/evaluations/{eval_id}",
                                 headers=self._key_auth(), name="robustness:poll",
                                 catch_response=True) as resp:
                if resp.status_code != 200:
                    resp.failure(f"rhd poll -> {resp.status_code}")
                    return
                if resp.json().get("status") in ("completed", "failed"):
                    return
            time.sleep(_PROFILE.poll_interval_s)

    @task(2)
    def exploit_search(self) -> None:
        if not self.ctx:
            return
        self.client.get("/v1/robustness/exploits/search", params={"q": "reward", "limit": 50},
                        headers=self._key_auth(), name="robustness:exploit_search")


class _PrefixedSession:
    """Adapter so api.bootstrap_tenant (which expects a Locust-style client with
    relative paths) can run against an absolute base URL via plain requests."""

    def __init__(self, session: requests.Session, base_url: str) -> None:
        self._s = session
        self._base = base_url.rstrip("/")

    def _ctx(self, resp):
        class _R:
            def __init__(self, r):
                self._r = r
                self.status_code = r.status_code

            def json(self):
                return self._r.json()

            def failure(self, *_args):  # parity with Locust's catch_response
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _R(resp)

    def post(self, path, **kw):
        kw.pop("name", None)
        kw.pop("catch_response", None)
        return self._ctx(self._s.post(self._base + path, **kw))

    def get(self, path, **kw):
        kw.pop("name", None)
        kw.pop("catch_response", None)
        return self._ctx(self._s.get(self._base + path, **kw))
