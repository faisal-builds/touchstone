"""Tests for the sandbox abstraction layer (ADR-002).

These exercise backend *selection*, the hardened OCI command construction, and
the runtime-availability preflight — none of which require a real gVisor or
Firecracker runtime to be installed. The subprocess backend's isolation
guarantees are covered separately in ``test_sandbox.py``.
"""

from __future__ import annotations

import pytest

from touchstone_verify.sandbox.base import (
    IsolationBackend,
    Sandbox,
    SandboxLimits,
    SandboxRuntimeUnavailable,
    build_sandbox,
)
from touchstone_verify.sandbox.oci import (
    FirecrackerSandbox,
    GvisorSandbox,
    OciSandbox,
)
from touchstone_verify.sandbox.runner import SandboxRunner


def test_subprocess_backend_is_default():
    sandbox = build_sandbox()
    assert isinstance(sandbox, SandboxRunner)
    assert isinstance(sandbox, Sandbox)  # satisfies the protocol


def test_backend_enum_accepts_strings():
    assert IsolationBackend("subprocess") is IsolationBackend.SUBPROCESS
    assert IsolationBackend("gvisor") is IsolationBackend.GVISOR
    assert IsolationBackend("firecracker") is IsolationBackend.FIRECRACKER


def test_all_backends_satisfy_the_protocol():
    for cls in (SandboxRunner, OciSandbox, GvisorSandbox, FirecrackerSandbox):
        assert hasattr(cls, "run")


def test_gvisor_uses_runsc_runtime():
    sandbox = GvisorSandbox()
    assert sandbox._runtime == "runsc"


def test_firecracker_uses_microvm_shim():
    sandbox = FirecrackerSandbox()
    assert sandbox._runtime == "kata-fc"


def test_oci_command_is_fully_locked_down():
    sandbox = GvisorSandbox(
        limits=SandboxLimits(memory_mb=128, max_processes=32, cpu_seconds=5),
        image="touchstone/sandbox:1.2.3",
    )
    cmd = sandbox.build_command("/tmp/job", "ts-sbx-abc")
    joined = " ".join(cmd)

    # The hardening flags an enterprise reviewer would check for.
    assert "--runtime=runsc" in cmd
    assert "--network=none" in cmd
    assert "--read-only" in cmd
    assert "--cap-drop=ALL" in cmd
    assert "--security-opt=no-new-privileges" in cmd
    assert "--user=65534:65534" in cmd
    assert "--pids-limit=32" in cmd
    assert "--memory=128m" in joined
    assert "/tmp/job:/job:ro" in joined
    assert cmd[-3:] == ["-I", "/job/_harness.py", "/job/job.json"]
    # Resource ulimits mirror the subprocess backend.
    assert "cpu=5:5" in joined
    assert "touchstone/sandbox:1.2.3" in cmd


def test_preflight_raises_when_tool_missing():
    sandbox = GvisorSandbox(container_tool="definitely-not-a-real-tool-xyz")
    with pytest.raises(SandboxRuntimeUnavailable):
        sandbox.preflight()


def test_hardened_backend_without_runtime_raises_by_default():
    # With a bogus container tool, the runtime is unavailable and (fallback off)
    # construction must fail loudly rather than silently weaken isolation.
    with pytest.raises(SandboxRuntimeUnavailable):
        _force_unavailable_gvisor(allow_fallback=False)


def test_hardened_backend_falls_back_when_permitted():
    sandbox = _force_unavailable_gvisor(allow_fallback=True)
    assert isinstance(sandbox, SandboxRunner)


def _force_unavailable_gvisor(*, allow_fallback: bool) -> Sandbox:
    import touchstone_verify.sandbox.oci as oci

    class _Unavailable(GvisorSandbox):
        def preflight(self) -> None:
            raise SandboxRuntimeUnavailable("forced for test")

    original = oci.GvisorSandbox
    oci.GvisorSandbox = _Unavailable  # type: ignore[misc]
    try:
        return build_sandbox(
            IsolationBackend.GVISOR, allow_fallback=allow_fallback
        )
    finally:
        oci.GvisorSandbox = original  # type: ignore[misc]
