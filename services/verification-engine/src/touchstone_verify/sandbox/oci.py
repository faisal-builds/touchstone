"""Hardened OCI-runtime sandbox backend (ADR-002, production).

Runs the verifier harness inside a single-shot, locked-down container under a
sandboxing OCI runtime. Two runtimes are supported through one abstraction:

* **gVisor** (``runsc``) — intercepts guest syscalls in a userspace kernel, so
  untrusted code never talks to the host kernel directly.
* **Firecracker** — a per-job microVM (via a firecracker/Kata containerd shim),
  giving hardware-virtualized isolation.

The container is started with: no network, read-only root filesystem, all Linux
capabilities dropped, ``no-new-privileges``, an unprivileged user, a pid limit,
memory/CPU caps, and POSIX ulimits mirroring the subprocess backend. The job
directory is mounted read-only; the harness emits its single JSON result line on
stdout, exactly as in the baseline backend, so :class:`SandboxResult` semantics
are identical across backends.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess  # noqa: S404 - used only for a fixed-arg runtime preflight
import tempfile
import uuid
from pathlib import Path

import structlog

from .base import SandboxRuntimeUnavailable
from .runner import SandboxLimits, SandboxResult

_HARNESS = Path(__file__).with_name("_harness.py")
_log = structlog.get_logger(__name__)


class OciSandbox:
    """Execute verifier code inside a hardened container under an OCI runtime."""

    def __init__(
        self,
        *,
        runtime: str,
        limits: SandboxLimits | None = None,
        image: str = "touchstone/sandbox:latest",
        container_tool: str = "docker",
        run_user: str = "65534:65534",  # nobody:nogroup
    ) -> None:
        self._runtime = runtime
        self._limits = limits or SandboxLimits()
        self._image = image
        self._tool = container_tool
        self._user = run_user

    # -- preflight -----------------------------------------------------------

    def preflight(self) -> None:
        """Verify the container tool and sandboxing runtime are usable.

        Raises :class:`SandboxRuntimeUnavailable` with an actionable message when
        either is missing, so a misconfigured production node fails loudly.
        """

        tool = shutil.which(self._tool)
        if tool is None:
            raise SandboxRuntimeUnavailable(
                f"container tool {self._tool!r} not found on PATH"
            )
        try:
            out = subprocess.run(  # noqa: S603 - fixed args, no shell
                [tool, "info", "--format", "{{json .Runtimes}}"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SandboxRuntimeUnavailable(
                f"could not query {self._tool} runtimes: {exc}"
            ) from exc
        if self._runtime not in (out.stdout or ""):
            raise SandboxRuntimeUnavailable(
                f"OCI runtime {self._runtime!r} is not registered with "
                f"{self._tool}; install it and register it (e.g. runsc for gVisor)"
            )

    # -- command construction (pure; unit-tested) ----------------------------

    def build_command(self, job_dir: str, container_name: str) -> list[str]:
        """Build the fully-locked-down container invocation for a job."""

        mb = "m"
        lim = self._limits
        return [
            self._tool, "run", "--rm",
            "--name", container_name,
            f"--runtime={self._runtime}",
            "--network=none",                       # no network at all
            "--read-only",                          # immutable root fs
            "--cap-drop=ALL",                       # no Linux capabilities
            "--security-opt=no-new-privileges",     # no setuid escalation
            f"--user={self._user}",                 # unprivileged
            f"--pids-limit={lim.max_processes}",    # anti fork-bomb
            f"--memory={lim.memory_mb}{mb}",        # memory cap
            "--memory-swap", f"{lim.memory_mb}{mb}",  # no swap beyond memory
            f"--cpus={max(1, lim.cpu_seconds // 5)}",  # CPU share
            "--ulimit", f"cpu={lim.cpu_seconds}:{lim.cpu_seconds}",
            "--ulimit", f"fsize={lim.max_file_size_mb * 1024 * 1024}",
            "--ulimit", f"nofile={lim.max_open_files}:{lim.max_open_files}",
            "--tmpfs", "/sandbox-tmp:rw,noexec,nosuid,size=16m",
            "-v", f"{job_dir}:/job:ro",             # job mounted read-only
            "--workdir", "/job",
            "--entrypoint", "python",
            self._image,
            "-I", "/job/_harness.py", "/job/job.json",
        ]

    # -- execution -----------------------------------------------------------

    async def run(self, code: str, artifact: object) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="ts-oci-")
        name = f"ts-sbx-{uuid.uuid4().hex[:16]}"
        try:
            with open(os.path.join(workdir, "job.json"), "w", encoding="utf-8") as fh:
                json.dump({"code": code, "artifact": artifact}, fh)
            # Copy the harness alongside the job so any minimal python image works.
            shutil.copyfile(_HARNESS, os.path.join(workdir, "_harness.py"))

            proc = await asyncio.create_subprocess_exec(
                *self.build_command(workdir, name),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._limits.wall_timeout_s
                )
            except TimeoutError:
                await self._force_kill(name, proc)
                return SandboxResult(ok=False, error="wall-clock timeout", timed_out=True)

            if proc.returncode != 0 and not stdout:
                msg = stderr.decode("utf-8", "replace")[:2000] or "non-zero exit"
                return SandboxResult(ok=False, error=msg, exit_code=proc.returncode)

            lines = stdout.decode("utf-8", "replace").strip().splitlines()
            if not lines:
                return SandboxResult(ok=False, error="no output from harness")
            try:
                payload = json.loads(lines[-1])
            except json.JSONDecodeError:
                return SandboxResult(ok=False, error="unparseable harness output")
            if not payload.get("ok"):
                return SandboxResult(ok=False, error=payload.get("error", "unknown"))
            return SandboxResult(ok=True, result=payload["result"], exit_code=0)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _force_kill(self, name: str, proc: asyncio.subprocess.Process) -> None:
        # Stop the container (the runtime owns the guest process tree), then the
        # client. Best-effort: a kill failure must not mask the timeout result.
        try:
            killer = await asyncio.create_subprocess_exec(
                self._tool, "kill", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=5)
        except (OSError, TimeoutError):
            _log.warning("sandbox.kill_failed", container=name)
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass


class GvisorSandbox(OciSandbox):
    """gVisor (``runsc``) backend — userspace-kernel syscall interception."""

    def __init__(self, *, limits: SandboxLimits | None = None,
                 image: str = "touchstone/sandbox:latest",
                 container_tool: str = "docker") -> None:
        super().__init__(runtime="runsc", limits=limits, image=image,
                         container_tool=container_tool)


class FirecrackerSandbox(OciSandbox):
    """Firecracker backend — a per-job microVM via a containerd shim runtime."""

    def __init__(self, *, limits: SandboxLimits | None = None,
                 image: str = "touchstone/sandbox:latest",
                 container_tool: str = "docker") -> None:
        # The runtime name is the containerd shim that fronts Firecracker/Kata.
        super().__init__(runtime="kata-fc", limits=limits, image=image,
                         container_tool=container_tool)
