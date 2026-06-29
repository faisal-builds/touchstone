#!/usr/bin/env python3
"""Touchstone end-to-end demo.

Drives the entire self-serve flow through the Python SDK against a running
Touchstone stack:

    signup -> create API key -> workspace -> project -> register verifier ->
    write artifact -> submit verification -> poll -> print result

Run it after starting the stack with ``make up`` (or ``docker compose up``):

    python scripts/demo.py

Configuration (env vars, all optional):
    TOUCHSTONE_BASE_URL        API base URL          (default http://localhost:8000)
    TOUCHSTONE_ARTIFACTS_DIR   host artifacts dir    (default ./.artifacts)

The artifacts dir must be the SAME directory the verification-engine has mounted
at /artifacts (the provided docker-compose.yml bind-mounts ./.artifacts), so the
engine can read the artifact this script writes. If the engine isn't running,
the script still completes signup→submit and reports the run as PENDING with a
hint, rather than hanging.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from touchstone import TouchstoneClient, TouchstoneError, VerificationStatus

BASE_URL = os.environ.get("TOUCHSTONE_BASE_URL", "http://localhost:8000")
ARTIFACTS_DIR = Path(os.environ.get("TOUCHSTONE_ARTIFACTS_DIR", "./.artifacts"))
POLL_TIMEOUT = float(os.environ.get("TOUCHSTONE_POLL_TIMEOUT", "20"))


def log(step: str, msg: str) -> None:
    print(f"\033[1;36m[{step}]\033[0m {msg}")


def main() -> int:
    sfx = uuid.uuid4().hex[:8]
    client = TouchstoneClient(BASE_URL)

    try:
        log("signup", f"creating user + org 'demo-{sfx}' ...")
        pair = client.signup(
            email=f"demo-{sfx}@example.com",
            password="correct horse battery staple",
            org_name=f"Demo Org {sfx}",
            org_slug=f"demo-{sfx}",
        )
        log("signup", f"got JWT, org={pair.org_slug}")

        log("apikey", "minting a member-scoped API key ...")
        key = client.create_api_key("demo-key", role="member")
        client.set_api_key(key.secret)
        log("apikey", f"key {key.key_id} created; now authenticating as the key")

        log("project", "creating workspace + project ...")
        ws = client.create_workspace("Demo Workspace", "demo-ws")
        project = client.create_project(ws.id, "Demo Project", "demo-project")

        log("verifier", "registering a deterministic code verifier ...")
        verifier = client.register_verifier(
            project.id,
            name="Answer Is 42",
            slug="answer-42",
            verifier_type="code",
            definition={
                "code": (
                    "def check(artifact):\n"
                    "    return {'score': 1.0 if artifact.get('answer') == 42 else 0.0}"
                ),
                "threshold": 1.0,
            },
        )
        log("verifier", f"registered {verifier.slug} v{verifier.version}")

        # Write the artifact where the verification-engine can read it.
        artifact_key = f"demo-{sfx}.json"
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS_DIR / artifact_key).write_text(json.dumps({"answer": 42}))
        log("artifact", f"wrote {ARTIFACTS_DIR / artifact_key}")

        log("submit", "submitting artifact for verification ...")
        run = client.submit_verification(verifier.id, artifact_ref=artifact_key)
        log("submit", f"run {run.id} status={run.status.value}")

        log("poll", "waiting for the verification-engine to grade it ...")
        try:
            result = client.wait_for_verification(run.id, timeout=POLL_TIMEOUT, interval=0.5)
        except TimeoutError:
            print()
            log("result", f"still PENDING after {POLL_TIMEOUT:g}s.")
            print(
                "  The control-plane accepted the run, but no verification-engine\n"
                "  picked it up. Start the full stack with `make up` (which runs the\n"
                "  engine and bind-mounts ./.artifacts), then re-run this demo."
            )
            return 0

        print("\n" + "=" * 56)
        print(f"  VERIFICATION {result.status.value.upper()}")
        print("=" * 56)
        if result.status == VerificationStatus.COMPLETED:
            print(f"  score        : {result.score}")
            print(f"  uncertainty  : {result.uncertainty}")
            print(f"  passed       : {result.passed}")
            print(f"  latency_ms   : {result.latency_ms}")
            print(f"  breakdown    : {result.grader_breakdown}")
        else:
            print(f"  the run FAILED; inspect run {result.id} for the error.")
        print("=" * 56)
        return 0

    except TouchstoneError as exc:
        log("error", f"{type(exc).__name__}: {exc.detail} (status={exc.status})")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
