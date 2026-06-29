"""Lease-store backend + the reusable conformance suite."""

from __future__ import annotations

import pytest

from touchstone_fleet import (
    InMemoryLeaseStore,
    run_lease_store_conformance,
)
from touchstone_fleet.coordination import FencingError, LeaseHeld


async def test_in_memory_store_passes_conformance():
    clock = {"t": 0.0}

    async def tick(seconds: float) -> None:
        clock["t"] += seconds

    store = InMemoryLeaseStore(clock=lambda: clock["t"])
    # If this returns without raising, the backend honors the full contract.
    await run_lease_store_conformance(store, tick=tick)


async def test_acquire_blocks_second_owner():
    store = InMemoryLeaseStore()
    await store.acquire("k", "a", ttl_s=100)
    with pytest.raises(LeaseHeld):
        await store.acquire("k", "b", ttl_s=100)


async def test_renew_rejects_stale_token():
    store = InMemoryLeaseStore()
    token = await store.acquire("k", "a", ttl_s=100)
    with pytest.raises(FencingError):
        await store.renew("k", "a", token=token + 5, ttl_s=100)
    await store.renew("k", "a", token=token, ttl_s=100)  # correct token ok


async def test_fencing_token_is_monotonic_across_takeovers():
    clock = {"t": 0.0}
    store = InMemoryLeaseStore(clock=lambda: clock["t"])
    t1 = await store.acquire("k", "a", ttl_s=10)
    clock["t"] = 11
    t2 = await store.acquire("k", "b", ttl_s=10)
    clock["t"] = 22
    t3 = await store.acquire("k", "c", ttl_s=10)
    assert t1 < t2 < t3
