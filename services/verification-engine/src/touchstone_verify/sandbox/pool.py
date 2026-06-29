"""Warm sandbox pool — pre-warmed, single-use isolated workers.

The per-call :class:`SandboxRunner` pays process-spawn + interpreter-startup on
every request — the dominant cost and the first thing to break a single-digit-ms
inline budget under load. The pool keeps ``min_size`` workers already spawned and
past interpreter startup, blocked on stdin; a request hands its job to a warm
worker (a *hit*), skipping that startup. If none are free and the pool is below
``max_size`` it spawns one on demand (a *cold spill*); above it, it raises so the
caller can shed/degrade rather than spawn unboundedly.

Isolation is preserved: workers are single-use (RLIMIT_CPU is cumulative; state
could leak across tenants), launched with ``python -I`` under an empty network
namespace when ``isolate_network`` is set, and apply rlimits in-process just
before running untrusted code. After each job the worker exits and the pool
refills toward ``min_size`` in the background.

``run(code, artifact)`` returns a :class:`SandboxResult`, so the pool is a
drop-in for :class:`SandboxRunner` in the inline fast path.

NOTE (honest scope): this is the *mechanism*. Its real p99 under production QPS,
the right pool sizes, and refill dynamics under bursty traffic can only be
established against live traffic — see the milestone's production-experience note.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .runner import SandboxLimits, SandboxResult, _kill_group

_POOL_WORKER = str(Path(__file__).with_name("_pool_worker.py"))


class PoolExhausted(RuntimeError):
    """No warm worker available and the pool is at max_size (backpressure)."""


@dataclass
class PoolStats:
    warm_hits: int = 0
    cold_spills: int = 0
    exhausted: int = 0
    spawned: int = 0
    recycled: int = 0


class _Worker:
    __slots__ = ("proc",)

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc


class WarmSandboxPool:
    def __init__(
        self, limits: SandboxLimits | None = None, *, min_size: int = 4,
        max_size: int = 32, isolate_network: bool = True,
    ) -> None:
        self._limits = limits or SandboxLimits()
        self._min = max(0, min_size)
        self._max = max(1, max_size)
        self._unshare = shutil.which("unshare") if isolate_network else None
        self._idle: collections.deque[_Worker] = collections.deque()
        self._total = 0  # idle + in-flight
        self._lock = asyncio.Lock()
        self._closed = False
        self._tasks: set[asyncio.Task] = set()
        self.stats = PoolStats()

    # --- lifecycle ----------------------------------------------------------
    @property
    def size(self) -> int:
        return self._total

    @property
    def idle(self) -> int:
        return len(self._idle)

    def _command(self) -> list[str]:
        base = [sys.executable, "-I", _POOL_WORKER]
        if self._unshare is not None:
            return [self._unshare, "--net", "--map-root-user", *base]
        return base

    async def _spawn(self) -> _Worker:
        proc = await asyncio.create_subprocess_exec(
            *self._command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        # Wait for the readiness sentinel so an idle worker is guaranteed past
        # interpreter startup (that is the whole point of "warm"). If we are
        # cancelled (e.g. aclose during refill) or it never readies, reap the
        # half-spawned process here so it is never orphaned.
        assert proc.stdout is not None
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            await self._reap(_Worker(proc))
            raise
        if not line or b"ready" not in line:
            await self._reap(_Worker(proc))
            raise RuntimeError("warm worker did not signal readiness")
        self.stats.spawned += 1
        return _Worker(proc)

    async def start(self) -> None:
        """Pre-warm the pool to ``min_size``."""
        async with self._lock:
            need = self._min - self._total
            workers = []
            for _ in range(max(0, need)):
                workers.append(await self._spawn())
                self._total += 1
            self._idle.extend(workers)

    async def _reap(self, worker: _Worker) -> None:
        proc = worker.proc
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()
        with contextlib.suppress(ProcessLookupError):
            proc.kill()          # closes the transport cleanly
        _kill_group(proc.pid)    # and the whole session (untrusted children)
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        # Close the underlying transport so its finalizer does not fire after the
        # event loop is gone (otherwise asyncio logs "Event loop is closed").
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()

    async def aclose(self) -> None:
        self._closed = True
        tasks = list(self._tasks)
        self._tasks.clear()
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        async with self._lock:
            workers = list(self._idle)
            self._idle.clear()
        for w in workers:
            await self._reap(w)
        self._total = 0

    # --- checkout / refill --------------------------------------------------
    async def _acquire(self) -> _Worker:
        async with self._lock:
            if self._idle:
                self.stats.warm_hits += 1
                return self._idle.popleft()
            if self._total >= self._max:
                self.stats.exhausted += 1
                raise PoolExhausted(f"warm pool at max_size ({self._max})")
            self._total += 1  # reserve a slot for the cold spill
            self.stats.cold_spills += 1
        # Spawn outside the lock (it awaits readiness).
        try:
            return await self._spawn()
        except Exception:
            async with self._lock:
                self._total -= 1
            raise

    def _schedule_refill(self) -> None:
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._refill_one())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _refill_one(self) -> None:
        async with self._lock:
            if self._closed or self._total >= self._min:
                return
            self._total += 1
        try:
            worker = await self._spawn()
        except Exception:
            async with self._lock:
                self._total -= 1
            return
        async with self._lock:
            if self._closed:
                # Raced with shutdown — don't leak a blocked worker.
                self._total -= 1
                _kill_group(worker.proc.pid)
                with contextlib.suppress(ProcessLookupError):
                    await worker.proc.wait()
                return
            self._idle.append(worker)

    async def run(self, code: str, artifact: object) -> SandboxResult:
        if self._closed:
            return SandboxResult(ok=False, error="pool closed")
        try:
            worker = await self._acquire()
        except PoolExhausted as exc:
            return SandboxResult(ok=False, error=str(exc))
        proc = worker.proc
        assert proc.stdin is not None
        assert proc.stdout is not None
        job = json.dumps({
            "code": code, "artifact": artifact,
            "limits": {
                "cpu_seconds": self._limits.cpu_seconds,
                "memory_mb": self._limits.memory_mb,
                "max_processes": self._limits.max_processes,
                "max_open_files": self._limits.max_open_files,
                "max_file_size_mb": self._limits.max_file_size_mb,
            },
        })
        try:
            proc.stdin.write((job + "\n").encode("utf-8"))
            await proc.stdin.drain()
            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=self._limits.wall_timeout_s
            )
        except TimeoutError:
            await self._reap(worker)
            self._release_slot()
            return SandboxResult(ok=False, error="wall-clock timeout", timed_out=True)
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self._reap(worker)
            self._release_slot()
            return SandboxResult(ok=False, error=f"worker died: {exc}")
        finally:
            for stream in (proc.stdin, proc.stdout):
                if stream is not None:
                    with contextlib.suppress(Exception):
                        stream.close()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()  # single-use: reap it
            transport = getattr(proc, "_transport", None)
            if transport is not None:
                with contextlib.suppress(Exception):
                    transport.close()

        self._release_slot()
        if not line:
            return SandboxResult(ok=False, error="no output from warm worker")
        try:
            payload = json.loads(line.decode("utf-8", "replace").strip())
        except json.JSONDecodeError:
            return SandboxResult(ok=False, error="unparseable warm-worker output")
        if not payload.get("ok"):
            return SandboxResult(ok=False, error=payload.get("error", "unknown"))
        return SandboxResult(ok=True, result=payload["result"], exit_code=0)

    def _release_slot(self) -> None:
        # The worker is single-use and now gone; free its slot and refill.
        self._total = max(0, self._total - 1)
        self.stats.recycled += 1
        self._schedule_refill()
