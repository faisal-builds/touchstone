"""The inline plane orchestrator.

One entry point — ``verify`` — runs the whole hot path: resolve policy, apply
backpressure and the latency budget, select robustness-trusted verifiers, run the
tiered executor under a circuit breaker, and produce a decision. Event emission
and artifact staging are returned for the caller to run in the background, so the
response is never blocked on the bus or object store.
"""

from __future__ import annotations

import random
import time

from .decision import DecisionEngine
from .events import InlineEventEmitter
from .execution import ResultCache, TieredExecutor
from .policy import PolicyEngine
from .resilience import Bulkhead, BulkheadFull, CircuitBreaker, LatencyBudget, fail_action
from .schemas import (
    Action,
    Decision,
    InlineVerifierRef,
    InlineVerifyRequest,
    Policy,
    sha256,
)
from .telemetry import record_decision, record_degradation


class PlaneResult:
    """A decision plus what to emit in the background."""

    def __init__(self, decision: Decision, policy: Policy, content: str,
                 escalations: list[InlineVerifierRef]) -> None:
        self.decision = decision
        self.policy = policy
        self.content = content
        self.escalations = escalations


class InlinePlane:
    def __init__(
        self, *, policy_engine: PolicyEngine, decision_engine: DecisionEngine,
        emitter: InlineEventEmitter, bulkhead: Bulkhead, breaker: CircuitBreaker,
        runner, cache: ResultCache, settings, enterprise=None,
    ) -> None:
        self._policies = policy_engine
        self._decisions = decision_engine
        self._emitter = emitter
        self._bulkhead = bulkhead
        self._breaker = breaker
        self._runner = runner
        self._cache = cache
        self._settings = settings
        self._enterprise = enterprise

    async def verify(self, org_id, req: InlineVerifyRequest) -> PlaneResult:
        policy = await self._policies.resolve(
            org_id, policy_id=req.policy_id, policy_slug=req.policy_slug
        )
        budget_ms = (
            req.latency_budget_ms or policy.latency_budget_ms
            or self._settings.default_latency_budget_ms
        )
        fail_mode = policy.fail_mode or self._settings.default_fail_mode.value
        mode = req.mode if req.mode in ("enforce", "shadow") else "enforce"
        budget = LatencyBudget(budget_ms)

        # Sampling: only a fraction of traffic is checked inline (the rest allowed).
        if (
            mode == "enforce"
            and policy.sampling_rate < 1.0
            and random.random() > policy.sampling_rate
        ):
            return self._degraded(policy, req.content, Action.ALLOW, budget,
                                  reason="sampled_out", fail_mode=fail_mode, mode=mode)

        # Backpressure: never queue — fail fast and degrade.
        try:
            self._bulkhead.acquire()
        except BulkheadFull:
            record_degradation("bulkhead_full", fail_mode)
            return self._degraded(policy, req.content, fail_action(fail_mode), budget,
                                  reason="bulkhead_full", fail_mode=fail_mode, mode=mode)
        try:
            return await self._run(org_id, req, policy, budget, fail_mode, mode)
        finally:
            self._bulkhead.release()

    async def _run(self, org_id, req, policy, budget, fail_mode, mode) -> PlaneResult:
        selected, routed_around = self._policies.select(policy)

        # Chaos failpoint: a game-day / test can arm "ivp.verify" to error here and
        # confirm the plane sheds via the breaker + fail mode rather than cascading.
        if self._enterprise is not None:
            try:
                self._enterprise.failpoint("ivp.verify")
            except Exception:
                self._breaker.record_failure()
                record_degradation("chaos_failpoint", fail_mode)
                return self._degraded(policy, req.content, fail_action(fail_mode), budget,
                                      reason="chaos_failpoint", fail_mode=fail_mode,
                                      mode=mode, routed_around=routed_around)

        if not self._breaker.allow():
            record_degradation("breaker_open", fail_mode)
            return self._degraded(policy, req.content, fail_action(fail_mode), budget,
                                  reason="breaker_open", fail_mode=fail_mode, mode=mode,
                                  routed_around=routed_around)

        executor = TieredExecutor(
            runner=self._runner, cache=self._cache, content_hash=sha256(req.content)
        )
        try:
            outcomes, escalations = await executor.execute(req.content, selected, budget)
            self._breaker.record_success()
        except Exception:  # a tier blew up — shed and degrade
            self._breaker.record_failure()
            record_degradation("tier_exception", fail_mode)
            return self._degraded(policy, req.content, fail_action(fail_mode), budget,
                                  reason="tier_exception", fail_mode=fail_mode, mode=mode,
                                  routed_around=routed_around)

        decision = self._decisions.decide(
            content=req.content, policy=policy, outcomes=outcomes, escalations=escalations,
            routed_around=routed_around, fail_mode=fail_mode, elapsed_ms=budget.elapsed_ms(),
            mode=mode,
        )
        if self._enterprise is not None:
            decision.reasons["region"] = self._enterprise.region_id
            self._enterprise.record_latency(decision.latency_ms)
        record_decision(decision.action.value, mode, budget.elapsed_ms() / 1000.0)
        return PlaneResult(decision, policy, req.content, escalations)

    def _degraded(self, policy, content, action: Action, budget, *, reason, fail_mode,
                  mode, routed_around=None) -> PlaneResult:
        decision = Decision(
            action=action, risk_score=(1.0 if action is Action.BLOCK else 0.0),
            risk_band=("critical" if action is Action.BLOCK else "low"),
            reasons={"cause": reason, "fail_mode": fail_mode,
                     "routed_around": [str(v) for v in (routed_around or [])]},
            latency_ms=round(budget.elapsed_ms(), 3), content_sha256=sha256(content),
            mode=mode, degraded=(reason != "sampled_out"),
        )
        record_decision(action.value, mode, budget.elapsed_ms() / 1000.0)
        return PlaneResult(decision, policy, content, [])

    async def emit(self, org_id, result: PlaneResult) -> None:
        """Run the background emission (decision audit + escalations)."""
        await self._emitter.emit_decision(org_id, result.policy, result.decision)
        await self._emitter.emit_escalations(
            org_id, result.policy, result.decision, result.content, result.escalations
        )


def now_ms() -> float:
    return time.monotonic() * 1000.0
