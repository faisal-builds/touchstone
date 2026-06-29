"""Sandbox execution harness — runs INSIDE the isolated subprocess.

This file is intentionally dependency-free and is launched with ``python -I``
(isolated mode: no PYTHONPATH, no user site-packages, no env-var influence) so
it shares nothing with the host application. It must never import host code.

Protocol:
  * argv[1] is a path to a JSON job file: {"code": <str>, "artifact": <any>}.
  * ``code`` must define ``check(artifact) -> dict`` returning at minimum
    ``{"score": float}`` and optionally ``passed`` / ``details``.
  * The harness prints a single JSON line to stdout:
    {"ok": true, "result": {...}}  or  {"ok": false, "error": "..."}

All resource limits (CPU, memory, processes, file size) and network isolation
are applied by the PARENT before exec; this file assumes it is already jailed.
"""

from __future__ import annotations

import json
import sys
import traceback


def _main() -> int:
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            job = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"job load failed: {exc}"}))
        return 0

    code = job.get("code", "")
    artifact = job.get("artifact")

    # Execute the untrusted verifier code in a fresh namespace. Builtins are
    # left available (rlimits + namespaces are the real boundary), but no host
    # globals are exposed.
    namespace: dict = {}
    try:
        compiled = compile(code, "<verifier>", "exec")
        exec(compiled, namespace)  # noqa: S102 — running customer-defined grader
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"compile/exec failed: {exc}"}))
        return 0

    check = namespace.get("check")
    if not callable(check):
        print(json.dumps({"ok": False, "error": "verifier defines no check(artifact)"}))
        return 0

    try:
        raw = check(artifact)
    except Exception:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "check() raised:\n" + traceback.format_exc()}))
        return 0

    if not isinstance(raw, dict) or "score" not in raw:
        print(json.dumps({"ok": False, "error": "check() must return {'score': float, ...}"}))
        return 0

    try:
        score = float(raw["score"])
    except (TypeError, ValueError):
        print(json.dumps({"ok": False, "error": "score is not numeric"}))
        return 0

    result = {
        "score": score,
        "passed": bool(raw.get("passed", score >= 1.0)),
        "details": raw.get("details", {}),
    }
    print(json.dumps({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
