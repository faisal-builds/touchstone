"""Distributed scheduler — region-aware, least-loaded placement with backpressure.

Places a unit of work onto a worker: prefer the caller's locality (via the
region router's failover chain), and within each region pick the least-loaded
healthy worker with spare capacity (least-connections). If no worker anywhere has
capacity, the job is shed (``NoCapacity``) so the caller degrades rather than
queues unboundedly — the same fail-fast posture as the inline bulkhead.

A placement reserves a slot on the chosen worker (``assign``); the caller releases
it on completion (``complete``). This is the placement *logic*; real work
transport, retries across regions, and behavior under saturation are production
concerns.
"""

from __future__ import annotations

import dataclasses

from .fleet import Worker, WorkerFleet
from .region import RegionRouter


class NoCapacity(RuntimeError):
    """No healthy worker with spare capacity in any region (backpressure)."""


@dataclasses.dataclass(frozen=True)
class Placement:
    worker_id: str
    region: str
    spilled: bool        # True if placed outside the preferred locality


class DistributedScheduler:
    def __init__(self, fleet: WorkerFleet, router: RegionRouter) -> None:
        self._fleet = fleet
        self._router = router

    @staticmethod
    def _least_loaded(workers: list[Worker]) -> Worker:
        return min(workers, key=lambda w: (w.load, -w.available))

    def place(self, *, locality: str | None = None) -> Placement:
        """Choose a worker following the region failover chain; least-loaded within.

        Does not mutate state — call :meth:`assign` to reserve the slot. Kept
        separate so a caller can inspect a placement (e.g. for logging) first.
        """
        chain = self._router.route(locality)  # ordered serving regions
        for idx, region in enumerate(chain):
            candidates = self._fleet.healthy(region.id)
            if candidates:
                worker = self._least_loaded(candidates)
                return Placement(worker_id=worker.id, region=region.id, spilled=idx > 0)
        raise NoCapacity("no worker with spare capacity in any serving region")

    def assign(self, *, locality: str | None = None) -> Placement:
        """Place and reserve a slot (increments in_flight on the chosen worker)."""
        placement = self.place(locality=locality)
        for w in self._fleet.all():
            if w.id == placement.worker_id:
                w.in_flight += 1
                break
        return placement

    def complete(self, worker_id: str) -> None:
        for w in self._fleet.all():
            if w.id == worker_id:
                w.in_flight = max(0, w.in_flight - 1)
                break
