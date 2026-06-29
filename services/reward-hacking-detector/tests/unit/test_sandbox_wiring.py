"""The RHD orchestrator runs verifier code through a configurable sandbox.

Attacks execute verifier code, so in production the orchestrator must use the
hardened gVisor/Firecracker backend rather than the subprocess baseline. These
tests cover backend selection from settings and injection into the orchestrator.
"""

from __future__ import annotations

from touchstone_verify.sandbox.base import IsolationBackend, Sandbox, build_sandbox
from touchstone_verify.sandbox.runner import SandboxRunner

from touchstone_rhd.config import Settings
from touchstone_rhd.orchestrator import Orchestrator


def test_settings_default_backend_is_subprocess():
    s = Settings()
    assert s.sandbox_backend is IsolationBackend.SUBPROCESS


def test_settings_accept_gvisor_backend(monkeypatch):
    monkeypatch.setenv("TOUCHSTONE_RHD_SANDBOX_BACKEND", "gvisor")
    monkeypatch.setenv("TOUCHSTONE_RHD_SANDBOX_ALLOW_FALLBACK", "true")
    s = Settings()
    assert s.sandbox_backend is IsolationBackend.GVISOR
    assert s.sandbox_allow_fallback is True


def test_orchestrator_uses_injected_sandbox():
    sentinel = SandboxRunner()
    orch = Orchestrator(sandbox=sentinel)
    assert orch._sandbox is sentinel  # type: ignore[attr-defined]


def test_orchestrator_default_is_a_sandbox():
    orch = Orchestrator()
    assert isinstance(orch._sandbox, Sandbox)  # type: ignore[attr-defined]


def test_production_wiring_builds_backend_from_settings():
    # Mirrors what app.py / worker_main do: build the configured backend. With a
    # gvisor request and fallback enabled (no runsc in CI), this resolves to the
    # subprocess baseline rather than raising — and is still a valid Sandbox.
    sandbox = build_sandbox(
        IsolationBackend.GVISOR, image="touchstone/sandbox:test", allow_fallback=True
    )
    assert isinstance(sandbox, Sandbox)
    orch = Orchestrator(sandbox=sandbox)
    assert orch._sandbox is sandbox  # type: ignore[attr-defined]
