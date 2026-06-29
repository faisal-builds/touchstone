# Master Roadmap

The path from the current tested foundation to a demonstrable end-to-end V1, and
the productionization beyond it. Phases are ordered by dependency; each is a
coherent, separately-shippable unit.

Legend: ✅ done · 🟡 partial · ⏳ not started

---

## Phase 0 — Architecture & control-plane foundation ✅
Monorepo, 14 frozen ADRs, event contracts, and the control-plane (tenancy,
RBAC, API-key + JWT auth, verifier registry, verification intake). 24 tests.

## Phase 1 — Verification engine ✅
Subprocess sandbox (verified isolation), four verifier families, ensemble
meta-verification, the consumer worker, results back to the run + emitted
events. 20 tests.

## Phase 2 — Self-serve + SDK ✅  *(this phase)*
- Signup / login endpoints minting JWTs, clean duplicate handling. ✅
- API-key creation reachable via the JWT user path. ✅
- Python SDK: typed client, auth, verifier registration, submit, poll, errors,
  README, tests. ✅
- End-to-end demo script. ✅
- Docs: README, PROJECT_STATUS, MASTER_ROADMAP. ✅

**Milestone reached:** the platform is self-serve and callable end to end by a
real client.

---

## Phase 3 — Close the event loop (risk + audit) ✅
Both consume events the engine emits; the backend loop is now closed.

- **risk-engine** ✅ — consumes `verification.completed`, computes a risk
  score/band from score + uncertainty (fail-floor rule), emits `risk.scored`,
  writes `risk_score` back to the run. 12 tests.
- **audit-engine** ✅ — per-org tamper-evident SHA-256 hash chain (ADR-011)
  recording all seven lifecycle events, with advisory-lock serialization,
  idempotency, and a per-org export/verify CLI. 10 tests.

## Phase 4 — Reward-hacking detector ✅
The **differentiated** subsystem, now built. An adversarial harness that attacks a
verifier with six families of crafted-to-fail artifacts (content corruption,
judge manipulation, length bias, formatting facades, edge cases, and a
model-generated adversary), runs them through the verifier (reusing the
verification-engine sandbox), detects which passes were reward hacks, and produces
a **robustness score** = 1 − exploit_rate with a Wilson confidence interval (plus
a severity-weighted variant). It writes the score back to
`verifier.robustness_score`, grows a deduplicated, **searchable** corpus of
exploits each **linked to the verifier version** it was found against (and
recording *why* the verifier failed), supports version comparison / regression
detection / trends, exposes an authenticated tenant-isolated API (launch / query /
search / compare / export), and runs a worker that auto-evaluates verifiers on
registration, recovers stranded jobs, and emits
`reward_hacking.robustness_evaluated`. 42 tests, including weak-vs-robust
discrimination through the real sandbox.

**Milestone reached:** the closed backend loop — authenticate → register verifier
→ submit → score + uncertainty + risk band + robustness rating + tamper-evident
audit entry. This is the "V1 backend complete" line.

## Phase 5 — TypeScript SDK ⏳
Generated from the OpenAPI 3.1 spec (which the control-plane already emits), to
mirror the Python SDK surface. _Medium._

## Phase 6 — Web dashboard (Next.js) ✅  *(this phase)*
The operator console — a Next.js 14 (App Router) backend-for-frontend that drives
the whole platform from a browser. ✅
- Auth/session (login, signup, httpOnly JWT cookie), middleware route guard. ✅
- Pages: overview, verifiers (list + detail with the signature Robustness Gauge,
  trend, launch-evaluation), runs, risk, robustness (evaluations + version
  compare), evaluation report (with export), searchable exploit corpus, audit
  trail, API keys, settings. Every surface handles loading / error / empty. ✅
- Type-safe client mirroring the backend contracts; BFF proxy attaching the
  session token; instrument-grade graphite-on-paper design. ✅
- The RHD was extended to accept the control-plane's user JWT (not just API keys)
  so the dashboard can call it; shared secret wired through docker-compose. ✅
- Gates: full production `next build`, strict TS, ESLint, 26 Vitest tests,
  Dockerfile (standalone), README. Not yet run end-to-end against live backends. ✅

## Phase 7 — Productionization ✅  *(this phase)*
The deploy layer and production hardening. Stable interfaces preserved across
every prior phase; backend test count rose from 131 → **146** (+9 sandbox-backend,
+2 security-headers, +4 dead-letter-queue) with all suites green and lint-clean.

- **Hardened sandbox** ✅ — a `Sandbox` protocol with the subprocess baseline kept
  intact and a config-selectable **gVisor (`runsc`) / Firecracker** OCI backend
  (locked-down container: no network, read-only root, caps dropped, unprivileged,
  pid/mem/cpu limits). Factory + preflight + command construction unit-tested
  (the runtimes themselves can't execute in the build sandbox). _Large._
- **Kubernetes + Helm** ✅ — full chart (per-service Deployments, Services,
  ConfigMap, Secret/ExternalSecret, HPA, PDB, Ingress, NetworkPolicy,
  ServiceMonitor, hardened security contexts) with production values + overlay;
  raw cluster scaffolding (namespace/PSS, quotas, RuntimeClass, default-deny).
- **Terraform (AWS)** ✅ — modular VPC / EKS (gVisor node group + IRSA) / RDS
  (multi-AZ) / ElastiCache (multi-AZ) / S3 / IAM / KMS / ACM / Secrets Manager.
- **Production security** ✅ — security headers, rate limiting, TLS at the ALB,
  JWT/secret management via External Secrets, audit logging.
- **Observability** ✅ — Prometheus metrics, opt-in OTel tracing, Grafana
  dashboard, alert rules, structured logging, health/readiness probes.
- **Reliability** ✅ — graceful shutdown, retries, a dead-letter queue for poison
  events, RDS/ElastiCache backups, and a disaster-recovery runbook.
- **CI/CD** ✅ — infra-validation workflow (helm/terraform/kubeconform/checkov)
  and a tag-driven release pipeline (image + chart publish, gated EKS deploy).
- **Docs** ✅ — deployment, operations, and disaster-recovery guides; README /
  PROJECT_STATUS / MASTER_ROADMAP updated.

The per-service-DB / single-writer split is **complete**: the RHD
robustness/exploits/replica tables and the audit-engine's `audit_records` are
owned by their services in their own databases with their own migrations; the
control-plane is the sole writer of `verifiers.robustness_score` (via an event
consumer) and reads `audit_records` read-only through a configurable
cross-database connection; and auth is federated (RHD validates API keys via the
control-plane introspection endpoint and reads no control-plane tables, so the
RHD and audit databases can be fully isolated). The load/perf **harness** for the
verification hot path is now built (a Locust suite under `load-tests/` with
smoke/local/staging/stress profiles, configurable thresholds, and a `perf-smoke`
CI job); production-representative numbers still need the live stack.
*(The S3 artifact backend and the RHD hardened-sandbox wiring — previously
deferred — are implemented; see below.)*

**Milestone reached:** the platform has a complete, enterprise-grade deployment
story — containerized, Helm-packaged, Terraform-provisioned, observable, and
recoverable.

---

## Phase 5 — TypeScript SDK ✅  *(this phase)*
The official `@touchstone/sdk` — a single strict-typed client over both the
control-plane and the reward-hacking-detector, generated from the OpenAPI 3.1
contracts and mirroring the Python SDK surface plus the robustness/exploit
endpoints. ✅
- Full surface: auth (signup/login), API keys, workspaces, projects, verifiers,
  verifications (+ `waitForVerification`), audit, and robustness
  (launch/get/report/list/trend/compare/search + `waitForEvaluation`). ✅
- Zero runtime dependencies (platform `fetch`); dual ESM + CJS builds with
  bundled `.d.ts`; injectable `fetch` for testing. ✅
- Typed error hierarchy mapped from RFC-7807 `problem+json`; polling helpers. ✅
- Gates: strict `tsc`, ESLint (zero warnings), 23 Vitest tests, `tsup` build,
  README, runnable `examples/demo.ts`, and a CI job. ✅

---

## Phase 8 — Inline Verification Plane (IVP) ✅  *(this phase)*

The final major V1 subsystem (ADR-015): turn Touchstone from offline *measurement*
into inline *control*. A new service, `services/ivp`, runs verifiers in the
critical path of live AI traffic and returns **allow / block / redact / escalate**
within a latency budget.
- **Gateway + policy engine** ✅ — synchronous `/v1/inline/verify` (+ streaming
  early-exit); epoch-versioned tenant policies; robustness-aware routing that
  **routes around gameable verifiers** using live RHD scores.
- **Tiered execution** ✅ — fast code-verifier tier inline in the sandbox (tight
  limits, dedup cache); model/process verifiers escalated to the async engine.
- **Decision engine** ✅ — robustness-weighted aggregation → risk-engine model →
  action; redaction; fail-closed on critical-verifier error.
- **Resilience** ✅ — bulkhead, circuit breaker, latency budget, per-policy
  fail-open/closed (mechanisms built; multi-region/SLO hardening is the live-mile).
- **Event integration** ✅ — `inline.decision` → audit chain; `inline.escalated` →
  verification-engine; `inline.evasion_observed` → RHD re-evaluation flywheel.
- **SDK middleware** ✅ — `InlineGuard` in Python and TypeScript.
- **Deploy** ✅ — 9th Helm workload (gVisor, inline ingress, HPA), Dockerfile, CI.
- Gates: 27 service tests + consumer tests across audit/verification/RHD, ruff +
  tsc + eslint clean. **Not** multi-region/SLA-hardened — that is the live-mile.

---

## Sequencing guidance

Phases 0–7 are done — the differentiated subsystem is built, the V1 backend loop
is closed end to end, the platform is driveable from a browser, both SDKs
(Python + TypeScript) ship, and there is a complete production deploy layer
(Helm, Terraform, K8s, CI/CD, observability, DR). What remains is the deferred
productionization refinements. The per-service-DB split is now **complete** (RHD
and the audit-engine own their tables/DBs/migrations, the control-plane is sole
writer of robustness_score and reads audit read-only cross-database, and auth is
federated so the RHD and audit databases can be fully isolated). What remains is
first live validation on real AWS/Kubernetes — including the load/perf harness
(now built) producing production-representative numbers against the live stack.
*(The two small backend gaps — the S3 `ArtifactStore` loader and the RHD
hardened-sandbox wiring — are done, behind the same interfaces and covered by
tests.)*
Sequence by what the next consumer or decision needs.
