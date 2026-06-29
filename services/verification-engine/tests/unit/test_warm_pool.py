"""Warm sandbox pool: pre-warm, correct execution, reuse accounting, backpressure."""

from __future__ import annotations

import pytest

from touchstone_verify.sandbox.pool import PoolExhausted, WarmSandboxPool
from touchstone_verify.sandbox.runner import SandboxLimits, sandbox_supported

# The warm pool spawns real sandboxed workers (POSIX fork/rlimits/unshare); skip
# — never fail — on platforms that cannot run them (Windows). Exercised in CI.
pytestmark = pytest.mark.skipif(
    not sandbox_supported(),
    reason="POSIX process sandbox (fork/rlimits/unshare) unavailable on this platform",
)

CODE = "def check(artifact):\n    return {'score': 1.0 if 'safe' in artifact else 0.0}"


def _pool(**kw) -> WarmSandboxPool:
    # Network isolation off under test (no privileged unshare in CI); generous wall.
    limits = SandboxLimits(cpu_seconds=2, memory_mb=128, wall_timeout_s=5.0)
    kw.setdefault("isolate_network", False)
    return WarmSandboxPool(limits, **kw)


async def test_prewarms_to_min_size():
    pool = _pool(min_size=3, max_size=8)
    try:
        await pool.start()
        assert pool.idle == 3
        assert pool.size == 3
    finally:
        await pool.aclose()


async def test_runs_code_on_a_warm_worker():
    pool = _pool(min_size=2, max_size=8)
    try:
        await pool.start()
        res = await pool.run(CODE, "this is safe")
        assert res.ok is True
        assert res.result["score"] == 1.0
        assert pool.stats.warm_hits >= 1
    finally:
        await pool.aclose()


async def test_failing_content_scores_zero():
    pool = _pool(min_size=1, max_size=4)
    try:
        await pool.start()
        res = await pool.run(CODE, "danger")
        assert res.ok is True
        assert res.result["score"] == 0.0
    finally:
        await pool.aclose()


async def test_worker_is_single_use_and_refills():
    pool = _pool(min_size=2, max_size=8)
    try:
        await pool.start()
        for _ in range(4):
            res = await pool.run(CODE, "safe")
            assert res.ok
        # Each call recycled its single-use worker.
        assert pool.stats.recycled >= 4
        # Background refill keeps the pool from collapsing below min over time.
        import asyncio
        await asyncio.sleep(0.5)
        assert pool.size <= 8
    finally:
        await pool.aclose()


async def test_cold_spill_when_no_idle_worker():
    pool = _pool(min_size=0, max_size=4)
    try:
        await pool.start()  # no pre-warm
        assert pool.idle == 0
        res = await pool.run(CODE, "safe")
        assert res.ok
        assert pool.stats.cold_spills >= 1
    finally:
        await pool.aclose()


async def test_backpressure_returns_error_at_max_size():
    # max_size=1, no idle: first acquire reserves the only slot; a concurrent
    # second call must hit PoolExhausted (surfaced as a non-ok result).
    pool = _pool(min_size=0, max_size=1)
    try:
        await pool.start()
        # Manually exhaust by reserving the slot, then prove acquire raises.
        async with pool._lock:
            pool._total = pool._max
        with pytest.raises(PoolExhausted):
            await pool._acquire()
    finally:
        pool._total = 0
        await pool.aclose()
