# Security Findings — Untrusted-Code Isolation

**Date:** 2026-06-30
**Scope:** Production-readiness blockers for untrusted-code isolation — the path from a
customer-authored verifier (`code` / `process` grader) to execution against untrusted input,
across the verification-engine sandbox, the inline plane (IVP), and the reward-hacking-detector (RHD).
**Status:** M1 + M2 fixed in PR #2 (`security/ivp-fail-closed`). M3 fixed in
`security/m3-limits-sanitize`. M4 partly contained (fail-closed IVP); egress backstop still open.

## Context

There are two sandbox backends:

- A **`subprocess` baseline** (rlimits + network namespace) in
  `services/verification-engine/src/touchstone_verify/sandbox/runner.py` and `pool.py`.
- A **hardened `gvisor` / `firecracker` backend** in
  `services/verification-engine/src/touchstone_verify/sandbox/oci.py`.

The hardened backend is well built. The problems below are about *which backend actually runs,
where, and what the baseline does not protect.*

---

## M1 — The inline plane runs customer code on live traffic but its sandbox-backend config is dead; it is permanently on the weak subprocess sandbox

**Severity: Critical — FIXED** (PR #2, `security/ivp-fail-closed`)

**Files:**
- `services/ivp/src/touchstone_ivp/main.py:50-68` — constructs `SandboxRunner(...)` (or `WarmSandboxPool`) directly
- `services/ivp/src/touchstone_ivp/config.py:83-84` — `sandbox_backend` / `sandbox_allow_fallback` defined but **never read**

**Description:** The IVP is the hot path that runs grader code against live AI traffic — the
highest-volume untrusted-input surface in the platform. Unlike the batch engine
(`verification-engine/main.py:49`) and RHD (`rhd/app.py:41`, `worker_main.py:31`), which both
call `build_sandbox(settings.sandbox_backend, …)` and therefore honor gVisor/Firecracker, the IVP
never calls `build_sandbox` at all. It hardcodes the subprocess backend. Worse, IVP's config
*exposes* `TOUCHSTONE_IVP_SANDBOX_BACKEND=gvisor` — so an operator who sets it to harden the inline
plane gets **no effect and no error**: a silent false sense of security. The syscall/VM barrier
ADR-002 promises does not exist on the one plane that needs it most.

**Recommended fix:** Wire the IVP runner through
`build_sandbox(settings.sandbox_backend, allow_fallback=settings.sandbox_allow_fallback, limits=…)`
exactly as the batch engine does, and have the warm pool wrap the selected backend rather than being
a parallel subprocess-only path. Until that exists, *remove* the dead
`sandbox_backend`/`sandbox_allow_fallback` fields from `ivp/config.py` so they cannot imply
protection that isn't there. Add a startup assertion that fails closed in `environment=production`
if the resolved backend is `subprocess`.

---

## M2 — The subprocess/warm-pool sandbox has no filesystem isolation: untrusted grader code can read host secrets

**Severity: Critical — FIXED** (PR #2, `security/ivp-fail-closed`) — was the *default* backend everywhere (`config.py:48`, `rhd/config.py:61` both defaulted to `SUBPROCESS`)

**Files:**
- `services/verification-engine/src/touchstone_verify/sandbox/runner.py:1-23` — threat model explicitly lists "read the host filesystem" as an attacker goal, but none of the five listed defenses (isolated interpreter, rlimits, net namespace, minimal env, wall-timeout) address filesystem access
- `services/verification-engine/src/touchstone_verify/sandbox/_harness.py:39-45` and `services/verification-engine/src/touchstone_verify/sandbox/_pool_worker.py:52-57` — `exec(compile(code,…), namespace)` with **full builtins available**

**Description:** On the subprocess and warm-pool backends, the untrusted `check(artifact)` runs as a
normal child process of the service user with an unrestricted view of the filesystem. Nothing stops
it from doing `open("/proc/self/environ")`, reading the mounted `.env`, the Kubernetes
service-account token at `/var/run/secrets/kubernetes.io/...`, `~/.aws/credentials`, or the JWT
signing secret, and returning the contents inside its own `details` field (which flows back as the
score payload) — a clean exfiltration channel even with the network namespace on. Because
`SUBPROCESS` is the default backend platform-wide and (per M1) the *only* backend the inline plane
can use, this is a live credential-theft path, not a theoretical one. The gVisor backend in
`oci.py` *does* isolate the FS (read-only root, only `/job` mounted ro), which is exactly why M1's
"gVisor is never reached inline" matters so much.

**Recommended fix:** Treat the subprocess backend as **non-production** — refuse to start with it
when `environment=production` (fail loud, as `base.py` already does for missing runtimes). Where it
must run (dev/CI), add a mount namespace + `chroot`/`pivot_root` into the empty job dir, or run the
harness under a seccomp profile that blocks `open`/`openat` outside the job dir. Strategically, make
`gvisor` the default `sandbox_backend` so the secure path is the one you get without extra
configuration.

---

## M3 — Customer-supplied `limits` in a verifier definition can disable network isolation and remove resource caps

**Severity: High — FIXED** (branch `security/m3-limits-sanitize`)

**Files:**
- `services/verification-engine/src/touchstone_verify/engine/code_verifier.py:41-42` — `limits = definition.get("limits") or {}; SandboxRunner(SandboxLimits(**limits))`
- `services/verification-engine/src/touchstone_verify/engine/process_verifier.py:53-54` — same pattern
- `services/verification-engine/src/touchstone_verify/sandbox/runner.py:64-72` — `SandboxLimits.isolate_network: bool = True` is a splattable field

**Description:** The verifier *definition* is customer-authored, and these constructors splat its
`limits` dict straight into `SandboxLimits`. The documented schema therefore lets a customer set
`"limits": {"isolate_network": false, "cpu_seconds": 100000, "memory_mb": 64000, "max_processes": 100000}`
— turning **off** the network namespace (enabling egress to `169.254.169.254` for cloud IAM creds,
or general data exfil) and lifting the caps that prevent node DoS. It is self-service
sandbox-weakening: the thing being sandboxed picks its own sandbox strength.

**Honest exploitability note:** In the *current* wiring, `VerifierFactory` always injects a shared
`runner`, so the `runner or SandboxRunner(**limits)` branch is bypassed and `limits` is effectively
ignored on the batch path; the IVP fast path doesn't go through `CodeVerifier` at all. So this is
**latent today** — but it's a documented public schema (`code_verifier.py` docstring shows `limits`)
that becomes a live escape the moment any caller honors per-verifier limits, which is the stated
intent ("Allow per-verifier sandbox tuning"). It also crashes verifier-build with an uncaught
`TypeError` on any unknown key.

**Recommended fix:** Never let customer input control isolation. Split the schema into *security*
limits (network isolation, max processes, memory ceiling — server-owned, non-overridable) and
*tuning* limits (timeouts within a server-enforced max). Validate/clamp the dict against an
allow-list and ignore `isolate_network` entirely from definitions. Reject unknown keys with a clear
error instead of `TypeError`.

**Fix applied:** Added `sanitize_definition_limits()` in `sandbox/runner.py`. Network isolation and
all resource caps (`isolate_network`, `memory_mb`, `max_processes`, `max_open_files`,
`max_file_size_mb`) are server-owned and **rejected** if a definition tries to set them; only
`cpu_seconds`/`wall_timeout_s` are tunable and are clamped to `[floor, server-default]` (can tighten,
never raise above the server max). Unknown/non-numeric keys raise a clear `ValueError` instead of the
silent `TypeError` a bare `SandboxLimits(**limits)` would throw. `CodeVerifier` and `ProcessVerifier`
call it **validate-always** — a definition that attempts to weaken isolation is rejected even on the
shared-runner path where the limits would otherwise be silently ignored, so the latent footgun is
removed rather than merely contained. Covered by `tests/unit/test_definition_limits.py`.

---

## M4 — Network isolation fails open silently when `unshare`/user-namespaces aren't available

**Severity: High**

**Files:**
- `services/verification-engine/src/touchstone_verify/sandbox/runner.py:110-118` — `self._unshare = shutil.which("unshare")`; if absent, the `unshare --net` wrapper is silently dropped
- `services/verification-engine/src/touchstone_verify/sandbox/pool.py:69,86-90` — same in the warm pool
- `services/ivp/src/touchstone_ivp/config.py:67` — `default_fail_mode = OPEN`

**Description:** Network isolation on the subprocess/pool backends is entirely contingent on
`unshare` being present and unprivileged user-namespaces being enabled on the host. If either is
false (a hardened host with `kernel.unprivileged_userns_clone=0`, a minimal container image without
`util-linux`), the sandbox **runs the untrusted code with full host network and only logs a
degradation** — `runner.py`'s own docstring says "defense degrades, not breaks." There is no egress
firewall as a backstop. Combined with the inline plane's fail-**open** default, a grader that needs
network simply has to land on such a node. The user-namespace path also runs the code as `uid 0`
inside the namespace (`--map-root-user`), which widens what a kernel-level bug in the *unsandboxed*
baseline could reach.

**Recommended fix:** Make network isolation mandatory in production — if `unshare`/userns is
unavailable, **fail closed** (raise, like `SandboxRuntimeUnavailable`) rather than running
unprotected. Add a network-policy / egress-deny backstop at the pod level so isolation does not
depend solely on a namespace the process itself sets up. Reconsider `--map-root-user` for the
baseline, and reconsider `fail_mode=OPEN` as the default for policies that gate on untrusted graders.

---

## Summary

| ID | Severity | Issue | Core file |
|----|----------|-------|-----------|
| **M1** | Critical — **FIXED** | Inline plane can't use the hardened sandbox; backend config is dead → subprocess-only on live traffic | `ivp/main.py:50`, `ivp/config.py:83` |
| **M2** | Critical — **FIXED** | Subprocess/pool sandbox = no filesystem isolation → host secret/cred theft (and it's the default backend) | `sandbox/runner.py`, `sandbox/_harness.py:39` |
| **M3** | High — **FIXED** | Customer-authored `limits` could disable network isolation / lift caps; now server-owned + validated always | `engine/code_verifier.py`, `sandbox/runner.py` |
| **M4** | High | Network isolation fails open silently without `unshare`/userns; IVP fails open | `sandbox/runner.py:110`, `ivp/config.py:67` |

## The throughline

The strong isolation (gVisor/Firecracker in `oci.py`) is real and correct, but (a) it's not
reachable on the inline plane and (b) `subprocess` — which deliberately does *not* contain a hostile
reader of the filesystem — is the platform-wide default. The single highest-leverage fix is to make
a hardened backend the default and **fail closed in production when it isn't active**, on *all three*
services including IVP. That one change neutralizes M1 and M2 and contains M3/M4.
