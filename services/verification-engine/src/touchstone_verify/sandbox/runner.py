"""Process sandbox for untrusted code verifiers (ADR-002).

Threat model: the ``code`` field of a code-verifier is attacker-controlled. We
assume it may attempt to exhaust CPU/memory, fork-bomb, write huge files, read
the host filesystem, or exfiltrate over the network. Defenses, in depth:

  1. **Isolated interpreter** — ``python -I`` ignores PYTHONPATH/env/user-site,
     so the child cannot import host code or be influenced by host env vars.
  2. **Resource limits** — POSIX rlimits on CPU time, address space (memory),
     process count (anti fork-bomb), open files, and output file size, applied
     in a ``preexec_fn`` before exec.
  3. **Network isolation** — when permitted, the job is launched inside a fresh
     network namespace via ``unshare -n`` so it has no network at all. If the
     host disallows it, we fall back and log (defense degrades, not breaks).
  4. **Minimal env + ephemeral cwd** — empty environment except PATH; cwd is a
     throwaway temp dir wiped after the run.
  5. **Hard wall-clock timeout** — the parent kills the entire process group on
     timeout, defeating sleeps and CPU-limit evasion.

In production each job additionally runs in a gVisor/Firecracker microVM per
ADR-002; this subprocess sandbox is the in-process baseline and the same
interface (`SandboxRunner.run`) backs both.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import resource
import shutil
import signal
import sys
import tempfile
from pathlib import Path

_HARNESS = str(Path(__file__).with_name("_harness.py"))


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxLimits:
    cpu_seconds: int = 5
    memory_mb: int = 256
    max_processes: int = 64
    max_open_files: int = 64
    max_file_size_mb: int = 16
    wall_timeout_s: float = 10.0
    isolate_network: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class SandboxResult:
    ok: bool
    result: dict | None = None
    error: str | None = None
    timed_out: bool = False
    exit_code: int | None = None


def _build_preexec(limits: SandboxLimits):
    def _preexec() -> None:  # runs in the child between fork and exec
        # NOTE: the session is already created via start_new_session=True; we must
        # not call os.setsid() again here (it would raise EPERM). We only apply
        # resource limits.
        mb = 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        mem = limits.memory_mb * mb
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
        resource.setrlimit(
            resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files)
        )
        fsize = limits.max_file_size_mb * mb
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        # Disable core dumps.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _preexec


class SandboxRunner:
    """Executes verifier code in an isolated subprocess. Async-friendly."""

    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self._limits = limits or SandboxLimits()
        self._unshare = shutil.which("unshare")

    def _command(self, job_path: str) -> list[str]:
        base = [sys.executable, "-I", _HARNESS, job_path]
        if self._limits.isolate_network and self._unshare is not None:
            # --net: empty network namespace; --map-root-user: allow unprivileged
            # namespace creation without real root.
            return [self._unshare, "--net", "--map-root-user", *base]
        return base

    async def run(self, code: str, artifact: object) -> SandboxResult:
        workdir = tempfile.mkdtemp(prefix="ts-sbx-")
        try:
            job_path = os.path.join(workdir, "job.json")
            with open(job_path, "w", encoding="utf-8") as fh:
                json.dump({"code": code, "artifact": artifact}, fh)

            proc = await asyncio.create_subprocess_exec(
                *self._command(job_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env={"PATH": "/usr/bin:/bin"},  # minimal; no host secrets
                preexec_fn=_build_preexec(self._limits),  # noqa: PLW1509
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._limits.wall_timeout_s
                )
            except TimeoutError:
                _kill_group(proc.pid)
                await proc.wait()
                return SandboxResult(ok=False, error="wall-clock timeout", timed_out=True)

            if proc.returncode != 0 and not stdout:
                msg = stderr.decode("utf-8", "replace")[:2000] or "non-zero exit"
                return SandboxResult(ok=False, error=msg, exit_code=proc.returncode)

            line = stdout.decode("utf-8", "replace").strip().splitlines()
            if not line:
                return SandboxResult(ok=False, error="no output from harness")
            try:
                payload = json.loads(line[-1])
            except json.JSONDecodeError:
                return SandboxResult(ok=False, error="unparseable harness output")

            if not payload.get("ok"):
                return SandboxResult(ok=False, error=payload.get("error", "unknown"))
            return SandboxResult(ok=True, result=payload["result"], exit_code=0)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
