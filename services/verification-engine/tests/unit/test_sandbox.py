"""Sandbox tests — these spawn real subprocesses and assert the isolation
guarantees actually hold (not just that the happy path works)."""

import pytest

from touchstone_verify.sandbox.runner import SandboxLimits, SandboxRunner


@pytest.mark.asyncio
async def test_valid_check_returns_score():
    runner = SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5))
    code = "def check(artifact):\n    return {'score': 1.0 if artifact == 42 else 0.0}"
    out = await runner.run(code, 42)
    assert out.ok
    assert out.result["score"] == 1.0


@pytest.mark.asyncio
async def test_failing_check_is_low_score_not_error():
    runner = SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5))
    code = "def check(artifact):\n    return {'score': 0.0, 'passed': False}"
    out = await runner.run(code, "anything")
    assert out.ok
    assert out.result["score"] == 0.0
    assert out.result["passed"] is False


@pytest.mark.asyncio
async def test_infinite_loop_is_killed_by_timeout():
    runner = SandboxRunner(SandboxLimits(cpu_seconds=1, wall_timeout_s=2))
    code = "def check(artifact):\n    while True:\n        pass"
    out = await runner.run(code, None)
    assert not out.ok
    # Either the CPU rlimit or the wall-clock timeout fires first; both are fine.
    assert out.timed_out or out.exit_code not in (0, None)


@pytest.mark.asyncio
async def test_memory_bomb_is_contained():
    runner = SandboxRunner(SandboxLimits(memory_mb=128, cpu_seconds=3, wall_timeout_s=6))
    code = "def check(artifact):\n    x = bytearray(1024*1024*1024)\n    return {'score': 1.0}"
    out = await runner.run(code, None)
    # The allocation must fail (MemoryError) -> not ok, but the host survives.
    assert not out.ok


@pytest.mark.asyncio
async def test_check_that_raises_is_reported():
    runner = SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5))
    code = "def check(artifact):\n    raise ValueError('boom')"
    out = await runner.run(code, None)
    assert not out.ok
    assert "boom" in (out.error or "")


@pytest.mark.asyncio
async def test_missing_check_function_is_reported():
    runner = SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5))
    out = await runner.run("x = 1", None)
    assert not out.ok
    assert "check" in (out.error or "").lower()
