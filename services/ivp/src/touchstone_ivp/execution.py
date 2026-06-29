"""Tiered verifier execution.

Inline verifiers run in tiers because model/process graders are too slow for the
hot path:

* **fast** — deterministic ``code`` verifiers executed in the sandbox within the
  latency budget, deduplicated by (verifier, content) and run concurrently;
* **slow** — model/process verifiers, *not* run inline; the executor emits them as
  escalations so the existing async verification-engine produces the deep verdict.

The fast tier reuses the verification-engine sandbox (the same isolation as the
batch engine) but with much tighter limits and a hard wall-clock cap, so a hostile
verifier cannot blow the caller's budget.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from touchstone_verify.sandbox.runner import SandboxRunner

from . import telemetry
from .resilience import LatencyBudget
from .schemas import InlineVerifierRef, Tier, VerifierOutcome


class ResultCache:
    """TTL + size-bounded cache of fast-tier outcomes keyed by content+verifier."""

    def __init__(self, *, max_entries: int, ttl_s: float, clock=time.monotonic) -> None:
        self._max = max_entries
        self._ttl = ttl_s
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, VerifierOutcome]] = OrderedDict()

    def get(self, key: str) -> VerifierOutcome | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        expires, outcome = hit
        if self._clock() >= expires:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return outcome

    def put(self, key: str, outcome: VerifierOutcome) -> None:
        self._data[key] = (self._clock() + self._ttl, outcome)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


def is_fast(ref: InlineVerifierRef) -> bool:
    """A verifier is inline-eligible if it is a code verifier and not slow-pinned."""
    has_code = bool(ref.definition and ref.definition.get("code"))
    return has_code and ref.tier in (Tier.FAST, Tier.AUTO)


class TieredExecutor:
    def __init__(self, *, runner: SandboxRunner, cache: ResultCache,
                 content_hash: str) -> None:
        self._runner = runner
        self._cache = cache
        self._chash = content_hash

    async def _run_one(
        self, content: str, ref: InlineVerifierRef, weight: float, budget: LatencyBudget,
    ) -> VerifierOutcome:
        key = f"{ref.verifier_id}:{self._chash}"
        cached = self._cache.get(key)
        if cached is not None:
            telemetry.record_cache(True)
            return cached.model_copy(update={"cached": True})
        telemetry.record_cache(False)

        started = time.monotonic()
        definition = ref.definition or {}
        code = definition["code"]
        threshold = float(definition.get("threshold", 1.0))
        remaining = budget.remaining_s()
        if remaining <= 0:
            telemetry.record_tier("fast", "budget_exceeded")
            return VerifierOutcome(
                verifier_id=ref.verifier_id, tier=Tier.FAST, weight=weight,
                critical=ref.critical, error="budget exhausted before run",
                latency_ms=(time.monotonic() - started) * 1000.0,
            )
        try:
            result = await asyncio.wait_for(self._runner.run(code, content), timeout=remaining)
        except TimeoutError:
            telemetry.record_tier("fast", "timeout")
            return VerifierOutcome(
                verifier_id=ref.verifier_id, tier=Tier.FAST, weight=weight,
                critical=ref.critical, error="verifier timed out",
                latency_ms=(time.monotonic() - started) * 1000.0,
            )

        latency_ms = (time.monotonic() - started) * 1000.0
        if not result.ok or result.result is None:
            telemetry.record_tier("fast", "error")
            return VerifierOutcome(
                verifier_id=ref.verifier_id, tier=Tier.FAST, weight=weight,
                critical=ref.critical, error=result.error or "sandbox failure",
                latency_ms=latency_ms,
            )
        payload = result.result
        score = max(0.0, min(1.0, float(payload.get("score", 0.0))))
        passed = bool(payload.get("passed", score >= threshold))
        outcome = VerifierOutcome(
            verifier_id=ref.verifier_id, tier=Tier.FAST, score=score, uncertainty=0.0,
            passed=passed, weight=weight, critical=ref.critical, latency_ms=latency_ms,
        )
        telemetry.record_tier("fast", "ok")
        self._cache.put(key, outcome)
        return outcome

    async def execute(
        self, content: str, selected: list[tuple[InlineVerifierRef, float]],
        budget: LatencyBudget,
    ) -> tuple[list[VerifierOutcome], list[InlineVerifierRef]]:
        """Run fast verifiers concurrently within the budget; collect escalations.

        Returns (fast_outcomes, slow_refs_to_escalate).
        """
        fast: list[tuple[InlineVerifierRef, float]] = []
        slow: list[InlineVerifierRef] = []
        for ref, weight in selected:
            if is_fast(ref):
                fast.append((ref, weight))
            else:
                slow.append(ref)

        outcomes: list[VerifierOutcome] = []
        if fast:
            outcomes = list(await asyncio.gather(
                *(self._run_one(content, ref, weight, budget) for ref, weight in fast)
            ))
        for _ in slow:
            telemetry.record_tier("slow", "escalated")
        return outcomes, slow
