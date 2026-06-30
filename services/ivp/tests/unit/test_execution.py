"""Tiered executor: real sandboxed fast-path, caching, and escalation."""

from __future__ import annotations

import uuid

import pytest
from touchstone_verify.sandbox.runner import SandboxLimits, SandboxRunner, sandbox_supported

from touchstone_ivp.execution import ResultCache, TieredExecutor
from touchstone_ivp.resilience import LatencyBudget
from touchstone_ivp.schemas import InlineVerifierRef, Tier, sha256

CODE = "def check(artifact):\n    return {'score': 1.0 if 'safe' in artifact else 0.0}"


def _runner() -> SandboxRunner:
    # The fast path executes verifier code in a real POSIX sandbox; tests that
    # build a runner skip where fork/rlimits are unavailable (Windows). Pure
    # cache/escalation tests that don't call this keep running.
    if not sandbox_supported():
        pytest.skip("POSIX process sandbox (fork/rlimits/unshare) unavailable on this platform")
    # Generous wall clock for subprocess startup under test; tight in production.
    return SandboxRunner(SandboxLimits(cpu_seconds=2, memory_mb=128, wall_timeout_s=5.0))


def _fast_ref() -> InlineVerifierRef:
    return InlineVerifierRef(verifier_id=uuid.uuid4(), tier=Tier.AUTO,
                             definition={"code": CODE, "threshold": 1.0})


async def test_fast_path_runs_code_verifier_in_sandbox():
    content = "this is safe"
    ex = TieredExecutor(runner=_runner(), cache=ResultCache(max_entries=64, ttl_s=30),
                        content_hash=sha256(content))
    ref = _fast_ref()
    outcomes, slow = await ex.execute(content, [(ref, 1.0)], LatencyBudget(5000))
    assert slow == []
    assert len(outcomes) == 1
    assert outcomes[0].score == 1.0
    assert outcomes[0].passed is True
    assert outcomes[0].cached is False


async def test_failing_content_scores_zero():
    content = "this is dangerous"
    ex = TieredExecutor(runner=_runner(), cache=ResultCache(max_entries=64, ttl_s=30),
                        content_hash=sha256(content))
    outcomes, _ = await ex.execute(content, [(_fast_ref(), 1.0)], LatencyBudget(5000))
    assert outcomes[0].score == 0.0
    assert outcomes[0].passed is False


async def test_second_run_is_cached():
    content = "this is safe"
    cache = ResultCache(max_entries=64, ttl_s=30)
    ex = TieredExecutor(runner=_runner(), cache=cache, content_hash=sha256(content))
    ref = _fast_ref()
    await ex.execute(content, [(ref, 1.0)], LatencyBudget(5000))
    outcomes, _ = await ex.execute(content, [(ref, 1.0)], LatencyBudget(5000))
    assert outcomes[0].cached is True


async def test_slow_verifier_is_escalated_not_run():
    content = "anything"
    ex = TieredExecutor(runner=_runner(), cache=ResultCache(max_entries=64, ttl_s=30),
                        content_hash=sha256(content))
    slow_ref = InlineVerifierRef(verifier_id=uuid.uuid4(), tier=Tier.SLOW)
    outcomes, slow = await ex.execute(content, [(slow_ref, 1.0)], LatencyBudget(5000))
    assert outcomes == []
    assert [r.verifier_id for r in slow] == [slow_ref.verifier_id]
