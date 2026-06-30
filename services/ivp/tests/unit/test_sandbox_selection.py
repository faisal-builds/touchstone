"""Inline sandbox selection: fail-closed wiring through build_sandbox.

These tests cover the selection logic in ``build_inline_runner`` (and the
``create_app`` wiring) without executing any sandbox, so they run on every
platform — including where the POSIX subprocess sandbox is unavailable.

Covered:
  (a) IVP selects the *configured* backend via build_sandbox, passing fast_* limits
  (b) it fails CLOSED when the backend runtime is unavailable (no silent fallback)
  (c) the warm pool is bypassed for hardened backends
  (d) the insecure subprocess path activates ONLY with the explicit env var
"""

from __future__ import annotations

import pytest
from touchstone_verify.sandbox.base import IsolationBackend, SandboxRuntimeUnavailable
from touchstone_verify.sandbox.pool import WarmSandboxPool
from touchstone_verify.sandbox.runner import SandboxRunner

from touchstone_ivp import main as ivp_main
from touchstone_ivp.config import Environment, Settings
from touchstone_ivp.main import (
    INSECURE_SANDBOX_ENV,
    InsecureSandboxError,
    build_inline_runner,
)


class _Sentinel:
    """Stand-in for a built hardened Sandbox; identity-checked in assertions."""

    async def run(self, code, artifact):  # pragma: no cover - never executed here
        raise AssertionError("not invoked in selection tests")


# --- (a) selects the configured backend, wiring through build_sandbox ----------

def test_selects_configured_hardened_backend_with_fast_limits(monkeypatch):
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    calls = {}
    sentinel = _Sentinel()

    def fake_build_sandbox(backend, *, limits, image, allow_fallback):
        calls.update(backend=backend, limits=limits, image=image,
                     allow_fallback=allow_fallback)
        return sentinel

    monkeypatch.setattr(ivp_main, "build_sandbox", fake_build_sandbox)

    settings = Settings(
        environment=Environment.CI, sandbox_backend="gvisor",
        fast_cpu_seconds=2, fast_memory_mb=99, fast_wall_timeout_s=0.25,
    )
    runner, warm_pool = build_inline_runner(settings)

    assert runner is sentinel
    assert warm_pool is None
    assert calls["backend"] is IsolationBackend.GVISOR
    # IVP's tight inline limits are threaded through, not the batch defaults.
    assert calls["limits"].cpu_seconds == 2
    assert calls["limits"].memory_mb == 99
    assert calls["limits"].wall_timeout_s == 0.25
    assert calls["image"] == settings.sandbox_image


def test_firecracker_backend_is_honored(monkeypatch):
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    seen = {}
    monkeypatch.setattr(
        ivp_main, "build_sandbox",
        lambda backend, **kw: seen.setdefault("backend", backend) or _Sentinel(),
    )
    settings = Settings(environment=Environment.CI, sandbox_backend="firecracker")
    build_inline_runner(settings)
    assert seen["backend"] is IsolationBackend.FIRECRACKER


# --- (b) fails closed when the hardened runtime is unavailable ------------------

def test_fails_closed_when_runtime_unavailable(monkeypatch):
    """A missing runtime must propagate, never degrade to subprocess."""
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)

    def boom(backend, **kw):
        raise SandboxRuntimeUnavailable("runsc not installed")

    monkeypatch.setattr(ivp_main, "build_sandbox", boom)
    settings = Settings(environment=Environment.CI, sandbox_backend="gvisor")

    with pytest.raises(SandboxRuntimeUnavailable):
        build_inline_runner(settings)


def test_hardened_backend_does_not_authorize_silent_fallback(monkeypatch):
    """Even with allow_fallback set, no insecure opt-in => allow_fallback=False
    is passed to build_sandbox, so it cannot silently downgrade to subprocess."""
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    seen = {}
    monkeypatch.setattr(
        ivp_main, "build_sandbox",
        lambda backend, **kw: seen.update(kw) or _Sentinel(),
    )
    settings = Settings(
        environment=Environment.CI, sandbox_backend="gvisor",
        sandbox_allow_fallback=True,  # operator asked for it...
    )
    build_inline_runner(settings)
    assert seen["allow_fallback"] is False  # ...but it's gated off without opt-in


def test_hardened_fallback_allowed_only_with_insecure_opt_in(monkeypatch):
    monkeypatch.setenv(INSECURE_SANDBOX_ENV, "1")
    seen = {}
    monkeypatch.setattr(
        ivp_main, "build_sandbox",
        lambda backend, **kw: seen.update(kw) or _Sentinel(),
    )
    settings = Settings(
        environment=Environment.CI, sandbox_backend="gvisor",
        sandbox_allow_fallback=True,
    )
    build_inline_runner(settings)
    assert seen["allow_fallback"] is True


# --- (c) warm pool bypassed for hardened backends ------------------------------

def test_warm_pool_bypassed_for_hardened_backend(monkeypatch):
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    sentinel = _Sentinel()
    monkeypatch.setattr(ivp_main, "build_sandbox", lambda backend, **kw: sentinel)

    settings = Settings(
        environment=Environment.CI, sandbox_backend="gvisor",
        warm_pool_enabled=True, warm_pool_min_size=2, warm_pool_max_size=8,
    )
    runner, warm_pool = build_inline_runner(settings)

    assert runner is sentinel
    assert warm_pool is None  # the subprocess-native pool is gated off
    assert not isinstance(runner, WarmSandboxPool)


# --- (d) insecure subprocess path requires the explicit env var ----------------

def test_subprocess_refused_without_opt_in(monkeypatch):
    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    settings = Settings(environment=Environment.CI, sandbox_backend="subprocess")
    with pytest.raises(InsecureSandboxError):
        build_inline_runner(settings)


def test_subprocess_allowed_with_opt_in(monkeypatch):
    monkeypatch.setenv(INSECURE_SANDBOX_ENV, "1")
    settings = Settings(environment=Environment.CI, sandbox_backend="subprocess")
    runner, warm_pool = build_inline_runner(settings)
    assert isinstance(runner, SandboxRunner)
    assert warm_pool is None


def test_subprocess_opt_in_keeps_warm_pool(monkeypatch):
    """The warm pool remains available on the explicitly-insecure dev path."""
    monkeypatch.setenv(INSECURE_SANDBOX_ENV, "1")
    settings = Settings(
        environment=Environment.CI, sandbox_backend="subprocess",
        warm_pool_enabled=True, warm_pool_min_size=2, warm_pool_max_size=8,
        warm_pool_isolate_network=False,
    )
    runner, warm_pool = build_inline_runner(settings)
    assert isinstance(runner, WarmSandboxPool)
    assert warm_pool is runner  # returned so the lifespan can start/close it


@pytest.mark.parametrize("value,allowed", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("nope", False),
])
def test_opt_in_truthiness(monkeypatch, value, allowed):
    monkeypatch.setenv(INSECURE_SANDBOX_ENV, value)
    settings = Settings(environment=Environment.CI, sandbox_backend="subprocess")
    if allowed:
        runner, _ = build_inline_runner(settings)
        assert isinstance(runner, SandboxRunner)
    else:
        with pytest.raises(InsecureSandboxError):
            build_inline_runner(settings)


# --- create_app-level wiring (fail closed end to end) --------------------------

def test_create_app_fails_closed_without_opt_in(monkeypatch):
    from touchstone_ivp.events import NullPublisher

    monkeypatch.delenv(INSECURE_SANDBOX_ENV, raising=False)
    with pytest.raises(InsecureSandboxError):
        ivp_main.create_app(
            Settings(environment=Environment.CI, sandbox_backend="subprocess"),
            publisher=NullPublisher(),
        )


def test_create_app_builds_with_opt_in(monkeypatch):
    from touchstone_ivp.events import NullPublisher

    monkeypatch.setenv(INSECURE_SANDBOX_ENV, "1")
    app = ivp_main.create_app(
        Settings(environment=Environment.CI, sandbox_backend="subprocess"),
        publisher=NullPublisher(),
    )
    assert app.state.plane is not None
