"""Warm-pool worker harness — a PRE-STARTED, single-use sandbox worker.

Unlike ``_harness.py`` (spawned per job), this process is started ahead of time
by :class:`WarmSandboxPool`, prints a ``{"ready": true}`` sentinel, and then
blocks reading one job from stdin. The expensive part — process spawn + Python
interpreter startup — therefore happens *before* the request arrives, off the hot
path. When a job is dispatched the worker applies resource limits in-process,
runs the grader exactly once, prints the result, and exits.

Single-use is deliberate: RLIMIT_CPU is cumulative and interpreter state could
leak across tenants, so a warm worker handles exactly one job. The pool keeps a
warm standby ready for the next request and refills in the background.

Launched with ``python -I`` (optionally under ``unshare --net``), so it shares no
PYTHONPATH/env with the host and — when network isolation is on — starts already
inside an empty network namespace.

Protocol (newline-delimited JSON over stdin/stdout):
  out: {"ready": true}
  in:  {"code": <str>, "artifact": <any>, "limits": {...}}
  out: {"ok": true, "result": {...}}  | {"ok": false, "error": "..."}
"""

from __future__ import annotations

import json
import resource
import sys
import traceback


def _apply_limits(limits: dict) -> None:
    mb = 1024 * 1024
    cpu = int(limits.get("cpu_seconds", 1))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    mem = int(limits.get("memory_mb", 128)) * mb
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    nproc = int(limits.get("max_processes", 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))
    nofile = int(limits.get("max_open_files", 64))
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    fsize = int(limits.get("max_file_size_mb", 10)) * mb
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _run(code: str, artifact: object) -> dict:
    namespace: dict = {}
    try:
        exec(compile(code, "<verifier>", "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"compile/exec failed: {exc}"}
    check = namespace.get("check")
    if not callable(check):
        return {"ok": False, "error": "verifier defines no check(artifact)"}
    try:
        raw = check(artifact)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "check() raised:\n" + traceback.format_exc()}
    if not isinstance(raw, dict) or "score" not in raw:
        return {"ok": False, "error": "check() must return {'score': float, ...}"}
    try:
        score = float(raw["score"])
    except (TypeError, ValueError):
        return {"ok": False, "error": "score is not numeric"}
    return {"ok": True, "result": {
        "score": score,
        "passed": bool(raw.get("passed", score >= 1.0)),
        "details": raw.get("details", {}),
    }}


def _main() -> int:
    _emit({"ready": True})
    line = sys.stdin.readline()
    if not line:
        return 0
    try:
        job = json.loads(line)
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "error": f"bad job: {exc}"})
        return 0
    # Constrain only now, once, just before running untrusted code.
    try:
        _apply_limits(job.get("limits") or {})
    except (ValueError, OSError) as exc:
        _emit({"ok": False, "error": f"limit setup failed: {exc}"})
        return 0
    _emit(_run(job.get("code", ""), job.get("artifact")))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
