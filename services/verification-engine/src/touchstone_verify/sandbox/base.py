"""Sandbox abstraction (ADR-002).

The verification engine executes attacker-controlled verifier code, so isolation
is a hard requirement. This module defines the **stable contract** every backend
implements and a factory that selects one from configuration:

    Sandbox.run(code: str, artifact: object) -> SandboxResult

Two backends ship:

* :class:`~touchstone_verify.sandbox.runner.SandboxRunner` — a subprocess
  backend (isolated interpreter + POSIX rlimits + network namespace). This is the
  in-process baseline used in dev/CI and as a fallback.
* :class:`~touchstone_verify.sandbox.oci.OciSandbox` — a production backend that
  runs the same harness inside a hardened OCI container under a sandboxing
  runtime (**gVisor** ``runsc`` or **Firecracker** via a microVM shim). This is
  the enterprise isolation boundary: a syscall-intercepting or VM-level barrier
  between untrusted code and the host kernel.

Switching backends is a configuration change, not a code change — every caller
depends only on the :class:`Sandbox` protocol and the shared
:class:`SandboxResult` / :class:`SandboxLimits` dataclasses.
"""

from __future__ import annotations

import enum
from typing import Protocol, runtime_checkable

import structlog

# The result/limit dataclasses live with the baseline backend; re-export them here
# so callers can depend on the abstraction module alone.
from .pool import PoolExhausted, PoolStats, WarmSandboxPool
from .runner import SandboxLimits, SandboxResult, SandboxRunner

__all__ = [
    "IsolationBackend",
    "Sandbox",
    "SandboxLimits",
    "SandboxResult",
    "SandboxRunner",
    "SandboxRuntimeUnavailable",
    "WarmSandboxPool",
    "PoolExhausted",
    "PoolStats",
    "build_sandbox",
]

_log = structlog.get_logger(__name__)


class SandboxRuntimeUnavailable(RuntimeError):
    """Raised when a hardened backend's runtime (e.g. ``runsc``) is not present."""


@runtime_checkable
class Sandbox(Protocol):
    """The stable execution contract. All backends are interchangeable."""

    async def run(self, code: str, artifact: object) -> SandboxResult: ...


class IsolationBackend(str, enum.Enum):
    """Selectable isolation backends, weakest to strongest isolation."""

    SUBPROCESS = "subprocess"  # baseline: rlimits + namespaces (dev/CI)
    GVISOR = "gvisor"          # production: gVisor (runsc) syscall interception
    FIRECRACKER = "firecracker"  # production: Firecracker microVM per job


def build_sandbox(
    backend: IsolationBackend | str = IsolationBackend.SUBPROCESS,
    *,
    limits: SandboxLimits | None = None,
    image: str = "touchstone/sandbox:latest",
    allow_fallback: bool = False,
) -> Sandbox:
    """Construct the configured sandbox backend.

    ``allow_fallback`` permits a hardened backend to degrade to the subprocess
    baseline when its runtime is unavailable (useful for non-prod clusters). In
    production this should stay ``False`` so a missing runtime fails loudly rather
    than silently weakening isolation.
    """

    backend = IsolationBackend(backend)
    limits = limits or SandboxLimits()

    if backend is IsolationBackend.SUBPROCESS:
        return SandboxRunner(limits)

    # Imported lazily so the baseline backend has no hard dependency on the OCI
    # backend's module-level imports.
    from .oci import FirecrackerSandbox, GvisorSandbox

    cls = GvisorSandbox if backend is IsolationBackend.GVISOR else FirecrackerSandbox
    try:
        sandbox = cls(limits=limits, image=image)
        sandbox.preflight()
        return sandbox
    except SandboxRuntimeUnavailable:
        if not allow_fallback:
            raise
        _log.warning(
            "sandbox.fallback",
            requested=backend.value,
            fallback="subprocess",
            reason="runtime_unavailable",
        )
        return SandboxRunner(limits)
