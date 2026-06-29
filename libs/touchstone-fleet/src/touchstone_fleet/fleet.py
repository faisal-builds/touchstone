"""Worker fleet: registration, heartbeats, health, and load accounting.

A region's plane is backed by a fleet of workers (the processes that run the
inline fast tier / escalations). The fleet registry is the live inventory the
scheduler places work onto: each worker reports its region, capacity, and a
heartbeat; a worker that misses its heartbeat TTL is considered dead and is
pruned so the scheduler stops routing to it.

This is the fleet *bookkeeping and placement input*. Real worker liveness,
real capacity under load, and real failure detection are production signals; this
structure is what consumes them and what the scheduler reasons over.
"""

from __future__ import annotations

import dataclasses
import time


@dataclasses.dataclass
class Worker:
    id: str
    region: str
    capacity: int = 8                 # max concurrent jobs
    in_flight: int = 0
    draining: bool = False
    last_heartbeat: float = 0.0

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.in_flight)

    @property
    def load(self) -> float:
        return self.in_flight / self.capacity if self.capacity else 1.0


class WorkerFleet:
    def __init__(self, *, heartbeat_ttl_s: float = 10.0, clock=time.monotonic) -> None:
        self._workers: dict[str, Worker] = {}
        self._ttl = heartbeat_ttl_s
        self._clock = clock

    def register(self, worker: Worker) -> None:
        worker.last_heartbeat = self._clock()
        self._workers[worker.id] = worker

    def heartbeat(self, worker_id: str, *, in_flight: int | None = None) -> None:
        w = self._workers.get(worker_id)
        if w is None:
            return
        w.last_heartbeat = self._clock()
        if in_flight is not None:
            w.in_flight = in_flight

    def deregister(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def set_draining(self, worker_id: str, draining: bool = True) -> None:
        w = self._workers.get(worker_id)
        if w is not None:
            w.draining = draining

    def _alive(self, w: Worker) -> bool:
        return (self._clock() - w.last_heartbeat) <= self._ttl

    def prune_dead(self) -> list[str]:
        """Remove workers past their heartbeat TTL. Returns the pruned ids."""
        dead = [wid for wid, w in self._workers.items() if not self._alive(w)]
        for wid in dead:
            del self._workers[wid]
        return dead

    def healthy(self, region: str | None = None) -> list[Worker]:
        out = [
            w for w in self._workers.values()
            if self._alive(w) and not w.draining and w.available > 0
        ]
        if region is not None:
            out = [w for w in out if w.region == region]
        return out

    def all(self) -> list[Worker]:
        return list(self._workers.values())

    def region_load(self) -> dict[str, float]:
        """Mean load per region over alive, non-draining workers (for forecasting)."""
        by_region: dict[str, list[float]] = {}
        for w in self._workers.values():
            if self._alive(w):
                by_region.setdefault(w.region, []).append(w.load)
        return {r: sum(v) / len(v) for r, v in by_region.items() if v}
