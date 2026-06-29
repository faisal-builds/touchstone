# Touchstone Inline Verification Plane (IVP)

The **inline/critical-path tier** of Touchstone. Where the rest of the platform
measures AI outputs offline, the IVP runs verifiers *in the request path* of live
AI/agent traffic and returns an **allow / block / redact / escalate** decision
within a configurable latency budget — then records every decision to the
tamper-evident audit chain.

See [ADR-015](../../docs/adr/015-inline-verification-plane.md) for the rationale.

## What it does

```
POST /v1/inline/verify
  { "policy_slug": "prod", "content": "<the live model output>" }
→ { "action": "block", "risk_score": 0.91, "risk_band": "critical",
    "reasons": {...}, "outcomes": [...], "latency_ms": 8.3,
    "content_sha256": "…", "decision_id": "…" }
```

* **allow** — passes the policy's verifiers within budget;
* **block** — aggregate risk ≥ the policy's `block_at`;
* **redact** — risk ≥ `redact_at`; the response carries `redacted_content`;
* **escalate** — a slow (model/process) verifier is required, or confidence is too
  low; the deep verdict returns asynchronously via `verification.completed`.

A streaming endpoint (`/v1/inline/verify/stream`) evaluates chunked output and
**early-exits** the moment a terminal verdict is reached, so a bad generation is
cut mid-stream.

## Architecture

| Concern | Module | Notes |
|---|---|---|
| Policy + routing | `policy.py` | Resolves the tenant policy; **routes around** verifiers whose RHD robustness score is below the policy floor; weights the rest by robustness. |
| Tiered execution | `execution.py` | Fast tier runs code verifiers in the verification-engine sandbox (tight limits) with a TTL/LRU cache; slow tier → escalation. |
| Decisioning | `decision.py` | Robustness-weighted aggregation → `touchstone_risk.RiskModel` → action; applies redaction rules. |
| Streaming | `streaming.py` | Accumulates chunks, re-evaluates, early-exits on block/redact. |
| Resilience | `resilience.py` | Bulkhead (backpressure), circuit breaker, latency budget, fail-open/closed. |
| Telemetry | `telemetry.py` | Prometheus: decision latency (SLO), action counts, tier/cache rates, degradations. |
| Auth | `auth.py` / `introspect.py` | `tsk_` keys validated via control-plane introspection (no control-plane DB reads); JWT supported. |
| Events | `events.py` | `inline.decision` → audit; `inline.escalated` → verification-engine; `inline.evasion_observed` → RHD. Off the hot path. |
| Orchestration | `plane.py` | One `verify()` entry runs the whole pipeline. |
| Gateway | `gateway.py` / `main.py` | FastAPI app + routes + `/healthz` `/readyz` `/metrics`. |

## Integration with the rest of Touchstone

* **control-plane** — introspects API keys; source of tenant config (policy loader hook).
* **verification-engine** — fast tier reuses its sandbox/code-verifier; consumes `inline.escalated` as the slow tier.
* **risk-engine** — its `RiskModel` is the inline decision model.
* **audit-engine** — consumes `inline.decision` into the hash chain ("prove what the AI was prevented from doing").
* **reward-hacking-detector** — robustness scores gate inline routing; consumes `inline.evasion_observed` to re-evaluate gameable verifiers (the flywheel).
* **SDKs** — `InlineGuard` (Python + TypeScript) wraps a model call: `enforce()` returns safe text or raises `Blocked`; `stream()` does chunked early-exit.

## Run it

```bash
pip install -e libs/touchstone-events -e services/verification-engine \
            -e services/risk-engine -e services/ivp
uvicorn touchstone_ivp.main:app --factory --port 8050
```

Config is environment-driven (prefix `TOUCHSTONE_IVP_`): `CONTROL_PLANE_URL`,
`DEFAULT_LATENCY_BUDGET_MS`, `DEFAULT_FAIL_MODE`, `MAX_CONCURRENT_INFLIGHT`,
`FAST_*` sandbox limits, `REDPANDA_BROKERS`. See `config.py`.

## Tests

```bash
cd services/ivp && PYTHONPATH=src pytest -q   # 27 tests (unit + gateway integration)
```

## Honest status

The data path, tiers, decisioning, resilience mechanisms, event loops, SDK
middleware, and audit integration are built, integrated, and locally tested. The
multi-region, SLA-backed, adversarially-hardened **production** maturity (latency
under real load, inline sandboxing at scale, failover, timing-attack hardening) is
the multi-year live-mile and is **not** done in-sandbox — those dimensions are
mechanisms-built-not-hardened, consistent with the rest of the repo's infra.
