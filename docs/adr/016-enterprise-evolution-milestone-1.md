# ADR-016 — Enterprise Evolution Program, Milestone 1

**Status:** Accepted (software mechanisms) · **Date:** 2026

## Context

The IVP (ADR-015) is a single-region inline plane. Taking it toward Fortune-500 /
major-lab use requires multi-region operation, a global control plane, fleet
scheduling, operational maturity, and the tooling to validate reliability.
Milestone 1 implements **every part of that which can be built and tested as
software**, and draws a hard line at everything that requires live production
operation.

## Decision

Add `libs/touchstone-fleet` — reusable, dependency-light primitives — and make the
IVP consume them:

* **Global control plane / policy distribution** (`distribution.py`): a monotonic,
  generation-ordered policy log at the center; each region holds a `RegionalReplica`
  that pulls deltas since its applied generation (last-writer-wins) and serves the
  hot path locally; a `DistributionCoordinator` exposes per-region lag and fleet
  convergence.
* **Multi-region + region-aware routing + active-active failover** (`region.py`):
  a `RegionRegistry` with health, and a `RegionRouter` that returns a locality-first,
  health-ranked failover chain.
* **Distributed scheduler + worker fleet** (`fleet.py`, `scheduler.py`):
  heartbeat-based fleet inventory with TTL pruning; least-loaded, region-aware
  placement with cross-region spill and fail-fast backpressure (`NoCapacity`).
* **Distributed state coordination** (`coordination.py`): fenced leases (single
  active owner, monotonic fencing tokens, TTL takeover) + a `FencedResource` that
  rejects stale-token writes — the split-brain defense.
* **Chaos engineering** (`chaos.py`): named **failpoints** + a `FaultInjector`
  (latency/error/drop, probabilistic, auto-disarm) + a `ChaosScenario`/`ChaosRunner`.
* **Advanced observability / SLO** (`slo.py`): objectives, error budgets, burn rate,
  multi-window burn-rate alerting.
* **Capacity forecasting + resource optimization** (`forecast.py`): EWMA + Holt
  linear-trend forecasting and a `CapacityPlanner` that recommends provisioning.

**IVP integration** (`services/ivp/enterprise.py`): an optional `EnterpriseContext`
gives the plane region identity (stamped on every decision), live SLO recording of
decision latency, and chaos failpoints in the hot path (an armed `ivp.verify` fault
makes the plane shed via the breaker + fail mode — proven by test). A new
`GET /v1/ops/status` exposes region, SLO attainment/error-budget/burn-rate,
resilience state, and warm-pool stats — the data behind the operations dashboard.
(Warm sandbox pools landed alongside this milestone in
`touchstone_verify.sandbox.pool`.)

## What is implemented software vs. what requires production

**Implemented software (built, locally tested, lint-clean):** every mechanism
above — routing/failover decisions, distribution + convergence, scheduling +
backpressure, lease fencing, chaos injection, SLO/error-budget/burn-rate math,
capacity forecasting, and the region-aware/SLO/chaos IVP integration.

**Requires live production experience (explicitly NOT done, NOT claimed):**
real cross-region transport and partition behavior; real health signals feeding the
registry; real worker liveness/capacity under load; warm-pool p99 at QPS; the SLO
numbers being *true* reliability rather than computed-from-synthetic-events; the
chaos *findings* (real blast radius, real correlations); capacity-forecast accuracy
against real demand; and active-active failover actually exercised against a live
region loss. These are the substance of Milestones 2+ and cannot be manufactured in
a sandbox.

## Consequences

## Addendum — M1 follow-on (M2 seams + operability)

Three risk-reducing follow-ons land on top of Milestone 1, all implemented software,
locally tested:

* **Lease-store seam** (`touchstone_fleet.store`): an async `LeaseStore` contract +
  in-memory backend + a reusable **conformance suite** any real backend
  (etcd/Consul/Dynamo) must pass before M2 trusts it. (The suite immediately caught
  a real fencing-token-monotonicity bug in the reference store — exactly its job.)
* **IVP ↔ regional replica** (`touchstone_ivp.distribution`): the plane's policy
  resolution now flows through the global control-plane log → per-region replica, so
  a policy authored in one region resolves in another (proven by test). Gated by
  `TOUCHSTONE_IVP_DISTRIBUTION_ENABLED`.
* **Enterprise operations dashboard** (`apps/web` → `/operations`): a page over
  `GET /v1/ops/status` showing region, SLO attainment/error-budget/burn-rate,
  resilience state, and warm-pool utilization; the dashboard reaches the IVP via
  `IVP_URL`.

These sharpen the seams M2 plugs into; they remain mechanisms, not production
validation.
