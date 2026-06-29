"""Global policy distribution.

The global control plane is the source of truth for inline policies; each region's
plane holds a local replica and must converge on the latest version without a
synchronous dependency on the center on the hot path. This module is the
*distribution protocol*: policies are versioned by a monotonic, global
**generation**; regions pull "everything since generation N" and apply it,
last-writer-wins per policy. Convergence is observable (per-region applied
generation), which is what active-active correctness and config-rollout safety
depend on.

This is the coordination *logic*. Cross-region transport, durable storage, and
real partition behavior are production capabilities; the in-memory store here has
the same interface a backed implementation would expose.
"""

from __future__ import annotations

import dataclasses
import threading


@dataclasses.dataclass(frozen=True)
class PolicyRecord:
    """An opaque, versioned policy blob keyed by id. ``generation`` is global and
    monotonic; ``epoch`` is the policy's own version (carried through for the IVP)."""

    policy_id: str
    org_id: str
    generation: int
    epoch: int
    payload: dict
    deleted: bool = False


class GlobalPolicyLog:
    """Append-only, generation-ordered log of policy versions (the center's truth)."""

    def __init__(self) -> None:
        self._gen = 0
        self._latest: dict[str, PolicyRecord] = {}
        self._lock = threading.Lock()

    @property
    def generation(self) -> int:
        return self._gen

    def publish(self, *, policy_id: str, org_id: str, epoch: int, payload: dict,
                deleted: bool = False) -> PolicyRecord:
        with self._lock:
            self._gen += 1
            rec = PolicyRecord(policy_id=policy_id, org_id=org_id, generation=self._gen,
                               epoch=epoch, payload=payload, deleted=deleted)
            self._latest[policy_id] = rec
            return rec

    def retire(self, *, policy_id: str, org_id: str, epoch: int) -> PolicyRecord:
        return self.publish(policy_id=policy_id, org_id=org_id, epoch=epoch,
                            payload={}, deleted=True)

    def since(self, generation: int) -> list[PolicyRecord]:
        """All current records with generation > the caller's applied generation."""
        with self._lock:
            return sorted(
                (r for r in self._latest.values() if r.generation > generation),
                key=lambda r: r.generation,
            )


class RegionalReplica:
    """A region's local, eventually-consistent view of the policy log.

    ``pull(log)`` fetches the delta since the last applied generation and applies
    it last-writer-wins. The hot path reads only this replica — never the center.
    """

    def __init__(self, region_id: str) -> None:
        self.region_id = region_id
        self._applied_gen = 0
        self._policies: dict[str, PolicyRecord] = {}

    @property
    def applied_generation(self) -> int:
        return self._applied_gen

    def get(self, policy_id: str) -> PolicyRecord | None:
        rec = self._policies.get(policy_id)
        if rec is None or rec.deleted:
            return None
        return rec

    def records(self) -> list[PolicyRecord]:
        """All current (non-deleted) policy records in this replica."""
        return [r for r in self._policies.values() if not r.deleted]

    def pull(self, log: GlobalPolicyLog) -> int:
        """Apply the delta from the center. Returns the number of records applied."""
        delta = log.since(self._applied_gen)
        for rec in delta:
            self._policies[rec.policy_id] = rec
            self._applied_gen = max(self._applied_gen, rec.generation)
        return len(delta)


class DistributionCoordinator:
    """Tracks convergence across regions: which generation each region has applied,
    and whether the fleet is fully converged on the center's latest generation."""

    def __init__(self, log: GlobalPolicyLog) -> None:
        self._log = log
        self._replicas: dict[str, RegionalReplica] = {}

    def register(self, replica: RegionalReplica) -> None:
        self._replicas[replica.region_id] = replica

    def propagate(self) -> dict[str, int]:
        """Push the latest delta to every region (a pull round). Returns per-region
        counts applied. In production this is each region polling on its own clock."""
        return {rid: r.pull(self._log) for rid, r in self._replicas.items()}

    def lag(self) -> dict[str, int]:
        """Generations each region is behind the center (0 == converged)."""
        target = self._log.generation
        return {rid: target - r.applied_generation for rid, r in self._replicas.items()}

    def converged(self) -> bool:
        return all(v == 0 for v in self.lag().values())
