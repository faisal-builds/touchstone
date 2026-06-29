"""Lease-store seam — the pluggable backend for distributed coordination.

``coordination.Lease`` is a correct *in-process* fenced lease. For real
multi-node coordination the lease must live in a shared store (etcd, Consul,
DynamoDB conditional writes, Redis). This module defines the **async store
contract** those backends implement, ships an in-memory backend with identical
semantics, and — crucially — a reusable **conformance suite** so any future
backend can be proven to honor the contract before it is trusted in M2.

Contract (the split-brain-safe invariants every backend must uphold):
  * at most one live owner per key;
  * an expired lease can be taken over;
  * every successful acquire returns a strictly increasing fencing token;
  * renew/release require the current owner (and renew the current token).
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable

from .coordination import FencingError, LeaseHeld


@runtime_checkable
class LeaseStore(Protocol):
    async def acquire(self, key: str, owner: str, ttl_s: float) -> int: ...
    async def renew(self, key: str, owner: str, token: int, ttl_s: float) -> None: ...
    async def release(self, key: str, owner: str) -> None: ...
    async def read(self, key: str) -> tuple[str | None, int]: ...


class InMemoryLeaseStore:
    """Reference :class:`LeaseStore` for tests and single-process use."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        # key -> (owner, expires_at)
        self._state: dict[str, tuple[str, float]] = {}
        # key -> highest fencing token ever issued (monotonic, survives release).
        self._tokens: dict[str, int] = {}

    def _live_owner(self, key: str) -> tuple[str | None, int]:
        token = self._tokens.get(key, 0)
        entry = self._state.get(key)
        if entry is None:
            return None, token
        owner, expires_at = entry
        if self._clock() >= expires_at:
            return None, token
        return owner, token

    async def acquire(self, key: str, owner: str, ttl_s: float) -> int:
        async with self._lock:
            live_owner, _ = self._live_owner(key)
            if live_owner is not None and live_owner != owner:
                raise LeaseHeld(f"lease {key} held by {live_owner}")
            token = self._tokens.get(key, 0) + 1
            self._tokens[key] = token
            self._state[key] = (owner, self._clock() + ttl_s)
            return token

    async def renew(self, key: str, owner: str, token: int, ttl_s: float) -> None:
        async with self._lock:
            live_owner, cur_token = self._live_owner(key)
            if live_owner != owner:
                raise LeaseHeld(f"lease {key} not held by {owner}")
            if token != cur_token:
                raise FencingError("stale fencing token on renew")
            self._state[key] = (owner, self._clock() + ttl_s)

    async def release(self, key: str, owner: str) -> None:
        async with self._lock:
            live_owner, _ = self._live_owner(key)
            if live_owner == owner:
                self._state.pop(key, None)  # token high-water is retained

    async def read(self, key: str) -> tuple[str | None, int]:
        async with self._lock:
            return self._live_owner(key)


async def run_lease_store_conformance(store: LeaseStore, *, tick) -> None:
    """Assert ``store`` honors the lease contract. ``tick(seconds)`` advances the
    store's clock (a coroutine; for real backends it sleeps). Backends call this
    from their own test suite — the single source of truth for correctness."""
    # 1. single owner
    t1 = await store.acquire("k", "a", ttl_s=10)
    try:
        await store.acquire("k", "b", ttl_s=10)
        raise AssertionError("expected LeaseHeld")
    except LeaseHeld:
        pass
    # 2. owner reads back; token is positive
    owner, token = await store.read("k")
    assert owner == "a" and token == t1 and t1 > 0

    # 3. renew requires the current token
    try:
        await store.renew("k", "a", token=t1 + 99, ttl_s=10)
        raise AssertionError("expected FencingError")
    except FencingError:
        pass
    await store.renew("k", "a", token=t1, ttl_s=10)

    # 4. takeover after expiry yields a strictly higher token
    await tick(11)
    expired_owner, _ = await store.read("k")
    assert expired_owner is None
    t2 = await store.acquire("k", "b", ttl_s=10)
    assert t2 > t1

    # 5. release frees the key for a fresh owner
    await store.release("k", "b")
    owner, _ = await store.read("k")
    assert owner is None
    t3 = await store.acquire("k", "c", ttl_s=10)
    assert t3 > t2
