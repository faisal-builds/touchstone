# ADR-015 — Inline Verification Plane (IVP)

**Status:** Accepted · **Date:** 2026 · **Supersedes:** none

## Context

Touchstone V1 (ADR-001…014) is an *offline* verification platform: callers submit
an artifact, the verification-engine grades it asynchronously over Redpanda, the
risk-engine scores it, the audit-engine records it, and the reward-hacking-detector
(RHD) measures how *gameable* each verifier is. This answers "was that output good?"
*after the fact*.

Enterprises running AI in production also need to act on outputs *in the request
path* — to block, redact, or escalate a bad generation before it reaches a user or
downstream agent — within a latency budget, and to prove what was prevented. That
is a different non-functional regime (synchronous, latency-bounded, fail-open/closed)
from the batch engine, but it should reuse the same verifiers, scoring, audit, and
robustness signal rather than fork them.

## Decision

Add a sixth runtime service — the **Inline Verification Plane (IVP)**,
`services/ivp` (`touchstone_ivp`) — as the inline/critical-path tier. It exposes a
synchronous gateway that, per a tenant **policy**, runs verifiers on a piece of live
content and returns one of **allow / block / redact / escalate** inside a configurable
latency budget, then records the decision to the audit chain.

Key design choices:

1. **Tiered execution.** A *fast* tier runs deterministic code verifiers inline in
   the verification-engine sandbox (tight CPU/mem/wall limits), deduplicated by
   (verifier, content-hash) and run concurrently under the budget. Model/process
   verifiers are *slow* and are **escalated** to the existing async engine rather
   than run inline. A *shadow* mode evaluates without enforcing.

2. **Robustness-aware routing (the moat).** The policy engine reads live RHD
   robustness scores and **routes around** verifiers below the policy's floor —
   putting a known-gameable grader in the critical path is worse than not checking.
   Trusted verifiers are robustness-weighted in the aggregate.

3. **Reuse, not fork.** The decision engine reuses `touchstone_risk.RiskModel`; the
   fast tier reuses `touchstone_verify` sandbox + code-verifier semantics; auth
   reuses the control-plane introspection federation (the IVP reads no control-plane
   tables, exactly like the RHD); content is hashed and never carried on the bus.

4. **Event integration.** Three new events on `Topic.INLINE`: `inline.decision`
   (→ audit-engine writes it to the tamper-evident chain — the compliance record),
   `inline.escalated` (→ verification-engine produces the deep verdict on its
   existing path), and `inline.evasion_observed` (→ RHD re-evaluates the implicated
   verifier — the adversarial flywheel). Emission and artifact staging happen off
   the hot path.

5. **Resilience as a first-class concern.** Per-policy fail-open/closed, a bulkhead
   for backpressure (fail-fast, never queue), a circuit breaker that sheds a failing
   tier, an epoch-versioned policy cache for config propagation, and graceful
   degradation. These are the *mechanisms* behind a multi-region/SLO posture.

6. **Form factors.** Both SDKs ship an `InlineGuard` middleware (`enforce()` →
   safe text or raises `Blocked`; `stream()` → chunked early-exit) so adoption is a
   few lines around an existing LLM call.

## Consequences

* Touchstone gains a *control* plane (stop the bad output) on top of the
  *measurement* plane, monetizable on traffic and sticky in the critical path.
* The IVP is independently scalable (`kind: web`, gVisor runtimeClass, aggressive
  HPA) and shares no database — it depends only on the control-plane (introspection)
  and the event bus.
* **Honest scope.** The data path, tiers, decisioning, resilience mechanisms, event
  loops, SDK middleware, and audit integration are built, integrated, and locally
  tested. The multi-region, SLA-backed, adversarially-hardened *production* maturity
  (real latency under load, inline sandboxing at scale, failover, timing-attack
  hardening) is the multi-year live-mile and is **not** claimed complete here; those
  dimensions are mechanisms-built-not-hardened, consistent with the rest of the
  infra (Helm/Terraform validated structurally, sandboxes command-constructed).
