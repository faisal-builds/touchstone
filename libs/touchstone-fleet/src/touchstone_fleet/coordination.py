"""Distributed state coordination — fenced leases.

Some fleet operations must have a single owner at a time (a config-rollout leader,
a region's scheduler primary, a migration runner). A **fenced lease** gives one
holder a time-bounded, monotonically-tokened grant: every acquisition mints a
strictly increasing *fencing token*, so a stale holder whose lease expired is
rejected by downstream resources that track the highest token seen — the standard
defense against the split-brain that naive locks allow.

This is the coordination *contract* with a correct in-memory implementation. A
production deployment backs it with a real consensus/lease store (etcd, Consul,
DynamoDB conditional writes); the semantics — single active holder, fencing
tokens, TTL expiry — are identical and are what callers program against.
"""

from __future__ import annotations

import time


class LeaseHeld(RuntimeError):
    """The lease is currently held by another owner."""


class FencingError(RuntimeError):
    """A write was attempted with a stale fencing token (split-brain defense)."""


class Lease:
    def __init__(self, key: str, *, ttl_s: float, clock=time.monotonic) -> None:
        self.key = key
        self._ttl = ttl_s
        self._clock = clock
        self._owner: str | None = None
        self._expires_at: float = 0.0
        self._token: int = 0

    def _expired(self) -> bool:
        return self._clock() >= self._expires_at

    @property
    def owner(self) -> str | None:
        return None if self._owner is not None and self._expired() else self._owner

    def acquire(self, owner: str) -> int:
        """Acquire (or take over an expired lease). Returns a fencing token."""
        if self._owner is not None and self._owner != owner and not self._expired():
            raise LeaseHeld(f"lease {self.key} held by {self._owner}")
        self._owner = owner
        self._expires_at = self._clock() + self._ttl
        self._token += 1
        return self._token

    def renew(self, owner: str, token: int) -> None:
        if self._owner != owner or self._expired():
            raise LeaseHeld(f"lease {self.key} not held by {owner}")
        if token != self._token:
            raise FencingError("stale fencing token on renew")
        self._expires_at = self._clock() + self._ttl

    def release(self, owner: str) -> None:
        if self._owner == owner:
            self._owner = None
            self._expires_at = 0.0


class FencedResource:
    """A resource that only accepts writes carrying the highest fencing token it
    has seen — so an expired leaseholder's late write is rejected."""

    def __init__(self) -> None:
        self._highest = 0

    def write(self, token: int, apply) -> None:
        if token < self._highest:
            raise FencingError(f"token {token} < highest seen {self._highest}")
        self._highest = token
        apply()
