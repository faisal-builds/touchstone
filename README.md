# Touchstone — the AI Verification Layer

Touchstone is the independent **verification / judgment layer** for AI: it
registers *verifiers* (graders, reward models, process supervisors), runs them
against AI outputs and trajectories, scores risk, records a tamper-evident
audit trail, and continuously hardens verifiers against reward hacking. It is
sold to frontier labs (for RL training signal) and to enterprises (for agent
deployment assurance).

> **Brand note:** the product was provisionally "BlackBox AI". That name
> communicates opacity — the opposite of this product — and collides with an
> existing AI coding assistant. The codebase uses the **Touchstone** brand
> (decoupled into the `PRODUCT_NAME` setting, so renaming is a one-line change).

## Repository layout (monorepo, ADR-001)

```
touchstone/
├─ services/
│  ├─ control-plane/          # ✅ V1 complete: tenancy, identity, RBAC, registry, verification intake
│  ├─ verification-engine/    # ✅ V1 complete: executes verifiers (code/model/process/hybrid), gVisor/Firecracker-capable sandbox, emits results
│  ├─ risk-engine/            # ✅ V1 complete: scores verification risk → risk.scored
│  ├─ audit-engine/           # ✅ V1 complete: tamper-evident hash-chained audit log
│  ├─ reward-hacking-detector/# ✅ V1 complete: adversarial verifier-robustness scoring
│  └─ ivp/                    # ✅ V1 complete: Inline Verification Plane — allow/block/redact/escalate on live AI traffic (ADR-015)
├─ libs/
│  ├─ touchstone-events/      # ✅ frozen cross-service event contracts (Redpanda)
│  └─ touchstone-common/      # shared utilities
├─ sdks/
│  ├─ python/                # ✅ typed Python SDK (touchstone-sdk): signup, keys, verifiers, submit, poll
│  └─ typescript/            # ✅ typed TypeScript SDK (@touchstone/sdk): full client over control-plane + RHD
├─ apps/web/                  # ✅ V1 complete: Next.js operator dashboard (BFF)
├─ deploy/                    # ✅ Productionized: Docker, Helm chart, Terraform (AWS), K8s manifests, observability
├─ load-tests/                # ✅ Locust load/performance suite (verification hot path; smoke/local/staging/stress)
├─ .github/workflows/         # ✅ CI (test + image build) + infra-validation + perf-smoke + release/deploy pipeline
└─ docs/                      # ADRs + deployment / operations / disaster-recovery guides
```

## Architecture at a glance

The **control-plane** is the system of record: organizations, workspaces,
projects, users, API keys, and the **verifier registry**. When an artifact is
submitted for verification, the control-plane persists a run and publishes a
`verification.requested` event to Redpanda. Downstream engines consume the
event stream independently:

```
            ┌──────────────┐   verification.requested   ┌──────────────────────┐
  client ──►│ control-plane │ ─────────────────────────► │ verification-engine  │
   (SDK)    └──────┬───────┘        (Redpanda)            └─────────┬────────────┘
                   │ Postgres                                       │ verification.completed
                   ▼                                                ▼
            tenancy + registry        ┌───────────────┬────────────┴──────────┐
            + run records             ▼               ▼                       ▼
                              risk-engine      audit-engine        reward-hacking-detector
                              (risk.scored)   (hash-chained)        (reward_hack.flagged)
```

Every event is an immutable, org-scoped `EventEnvelope` (see
`libs/touchstone-events`) — the single source of truth for the wire format. The
backend loop is closed: a submitted verification flows through the
verification-engine (grading), the risk-engine (`risk.scored`, written back to
the run), and the audit-engine (every step recorded into a per-org tamper-evident
hash chain). Export and verify an organization's audit chain with the audit CLI:

```bash
python -m touchstone_audit.cli export --org <org-uuid>   # ordered chain as JSON
python -m touchstone_audit.cli verify --org <org-uuid>   # recompute + integrity check
```

## Quickstart

```bash
# 1. Bring up the full stack (Postgres, Redis, Redpanda, API) in Docker
make up

# API is now live:
curl localhost:8000/healthz
open  localhost:8000/docs        # OpenAPI 3.1 docs

# --- or run the service directly against local infra ---
make install                     # venv + editable installs
make migrate                     # apply DB schema
make run                         # uvicorn with autoreload
```

## Self-serve quickstart (Python SDK)

The platform is callable end to end by a real client. Install the SDK and run
the full loop:

```python
from touchstone import TouchstoneClient

client = TouchstoneClient("http://localhost:8000")
client.signup(email="founder@acme.com", password="correct horse battery staple",
              org_name="Acme", org_slug="acme")          # returns + stores a JWT
key = client.create_api_key("ci", role="member"); client.set_api_key(key.secret)
ws = client.create_workspace("Research", "research")
project = client.create_project(ws.id, "Coding Agent", "coding-agent")
verifier = client.register_verifier(
    project.id, "Answer 42", "answer-42", "code",
    {"code": "def check(a):\n return {'score': 1.0 if a.get('answer')==42 else 0.0}",
     "threshold": 1.0})
run = client.submit_verification(verifier.id, artifact_ref="demo/run.json")
result = client.wait_for_verification(run.id)
print(result.status, result.score, result.passed)
```

See `sdks/python/README.md` for the full SDK reference.

A **TypeScript SDK** (`@touchstone/sdk`) mirrors the same surface for JS/TS
consumers — a single typed client over both the control-plane and the
reward-hacking-detector, with dual ESM/CJS builds and zero runtime dependencies.
See `sdks/typescript/README.md`.

## Run the end-to-end demo locally

`scripts/demo.py` drives the entire flow (signup → API key → project → verifier →
submit → poll → print result) through the SDK.

```bash
# 1. Start the full stack (Postgres, Redis, Redpanda, control-plane, engine).
#    The engine bind-mounts ./.artifacts, which the demo writes into.
make up

# 2. Install the SDK into your environment, then run the demo.
make install
make demo            # or: python scripts/demo.py
```

The demo prints each step and, once the verification-engine grades the artifact,
the final score / uncertainty / pass-fail. If you run only the control-plane
(no engine), the demo still completes through submission and reports the run as
`PENDING` with a hint, rather than hanging.

Configuration (all optional env vars): `TOUCHSTONE_BASE_URL` (default
`http://localhost:8000`), `TOUCHSTONE_ARTIFACTS_DIR` (default `./.artifacts`,
must match the engine's mounted volume), `TOUCHSTONE_POLL_TIMEOUT` (seconds).

## Testing

```bash
make test-unit     # pure logic, no infra (RBAC + crypto)
make test          # full suite incl. integration against Postgres
```

### Load & performance

A [Locust](https://locust.io/) suite under `load-tests/` exercises the
verification hot path (submit → poll → completion) plus the control-plane and
reward-hacking-detector surfaces, with `smoke`/`local`/`staging`/`stress`
profiles and configurable pass/fail thresholds (p95/p99, error rate, timeout
rate, completion time):

```bash
pip install -e load-tests
cd load-tests && ./run.sh local      # smoke | local | staging | stress
```

A lightweight `perf-smoke` CI workflow runs the `smoke` profile against the
control-plane API on every change. Local/CI numbers are indicative only; the
production-representative numbers come from running `staging`/`stress` against a
real cluster during live validation. See `load-tests/README.md`.

The V1 control-plane ships with auth + tenancy + the verifier registry; the
verification-engine executes verifiers in a real sandbox; the risk-engine scores
each verification; the audit-engine records every step into a tamper-evident hash
chain; the reward-hacking-detector measures how robust each verifier is against
manipulation; the Python SDK makes the platform callable end to end; and a
Next.js operator dashboard drives the whole platform from a browser. The
backend event loop is closed. The repo ships with **146 backend tests** plus
**26 dashboard tests**: exhaustive RBAC + crypto unit tests, a real subprocess
sandbox whose isolation
guarantees are verified by tests that trigger them, ensemble meta-verification,
the risk model, the audit hash chain (including tamper-detection and idempotency),
the reward-hacking detector (proving it tells a gameable verifier from a robust
one through the real sandbox), and HTTP/SDK integration tests (against real
Postgres) asserting cross-tenant isolation, the signup→login→key flow, and the
full self-serve loop.

## Status

`control-plane`, `verification-engine`, `risk-engine`, `audit-engine`,
`reward-hacking-detector`, the event contracts, the Python SDK, and the
`apps/web` operator dashboard are production-runnable and tested (**146 backend
tests** plus **26 dashboard tests** across the platform,
including a real subprocess sandbox whose isolation guarantees — CPU/memory
limits, network isolation, timeouts — are verified by tests that actually trigger
them, an audit hash chain whose tamper-detection is verified by tests that tamper
with it, and a reward-hacking detector whose robustness scoring is verified by
tests that show it separating a gameable verifier from a robust one). The
dashboard is a backend-for-frontend that drives the platform from a browser;
its correctness is gated by a full production build, strict typechecking, and a
Vitest suite, though it has not been run end-to-end against live backends in this
environment. Both SDKs — Python and TypeScript — are built and tested.

## Productionization (Phase 7) ✅

The platform now ships a complete deploy layer and production hardening:

- **Hardened sandbox** — a stable `Sandbox` contract with a subprocess baseline
  (dev/CI) and a config-selectable **gVisor (`runsc`) / Firecracker** OCI backend
  for production isolation of untrusted verifier code (ADR-002). The hardened
  backends are real, locked-down container invocations (no network, read-only
  root, all caps dropped, unprivileged user, pid/memory/cpu limits); they cannot
  be *executed* in this build sandbox (no container runtime) but their command
  construction and runtime preflight are unit-tested.
- **Kubernetes / Helm** — a full chart rendering per-service Deployments,
  Services, ConfigMap/ExternalSecret, HPAs, PodDisruptionBudgets, Ingress (ALB +
  ACM TLS), NetworkPolicies, and ServiceMonitors, with hardened pod/container
  security contexts; plus raw cluster scaffolding (namespace with restricted PSS,
  quotas, gVisor RuntimeClass, baseline default-deny).
- **Terraform (AWS)** — modular VPC, EKS (with a tainted gVisor node group and
  IRSA), multi-AZ RDS PostgreSQL, multi-AZ ElastiCache Redis, an encrypted
  versioned S3 artifact bucket, IAM/IRSA roles, KMS, ACM, and a Secrets Manager
  bundle.
- **Security** — security-headers middleware (HSTS/CSP/etc.), Redis rate
  limiting, JWT secret management via External Secrets, TLS at the ALB, and the
  tamper-evident audit chain.
- **Observability** — Prometheus metrics (`touchstone_http_*`), opt-in OTel
  tracing, a Grafana dashboard, alert rules, structured logging, and
  health/readiness probes on every service.
- **Reliability** — graceful shutdown (SIGTERM), worker retries, a dead-letter
  queue for poison events, and RDS/ElastiCache backups + a documented DR plan.
- **CI/CD** — the existing test/build CI plus an infra-validation workflow
  (helm lint/template/kubeconform, terraform fmt/validate/tflint, checkov) and a
  tag-driven release pipeline (image + chart publish, gated EKS deploy).

> **Honest scope note:** this is a tested engineering *foundation* with a
> production deploy layer, not a shipped product. The reward-hacking detector
> measures robustness against a built-in catalogue of attack strategies; whether
> that catalogue covers what a determined real-world attacker would find is an
> empirical question that grows with the corpus. The infra (Helm/Terraform/K8s)
> is validated structurally and by careful construction — **not** by live
> `helm lint` / `terraform validate` / `kubectl` (those tools aren't available in
> this build sandbox); the `infra-validation` workflow runs them for real in CI.
> The live multi-service event flow is proven per-service rather than over a
> running broker, and the gVisor/Firecracker backends can't be executed here for
> the same reason. Whether labs trust an independent grader remains
> organizational, and lives outside this codebase.
