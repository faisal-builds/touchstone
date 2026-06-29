"""Regions: registry, health, region-aware routing, and active-active failover.

A multi-region IVP runs an independent plane in each region. This module decides
*which region serves a request* and *what happens when a region is unhealthy*.

Routing is locality-first (serve from the caller's nearest healthy region) with
active-active failover: if the preferred region is unhealthy or draining, traffic
spills to the next healthy region by weight, deterministically. Health is a
push/poll input here — the *signal* (real health checks, real failover) is a
production capability; this module is the decision logic that consumes it.
"""

from __future__ import annotations

import dataclasses
import enum


class RegionStatus(str, enum.Enum):
    HEALTHY = "healthy"      # serving
    DEGRADED = "degraded"    # serving but deprioritized
    DRAINING = "draining"    # finish in-flight, take no new traffic
    DOWN = "down"            # not serving


@dataclasses.dataclass
class Region:
    id: str                      # e.g. "us-east-1"
    locality: str                # e.g. "na" | "eu" | "apac"
    weight: float = 1.0          # relative capacity within a locality
    status: RegionStatus = RegionStatus.HEALTHY

    @property
    def serving(self) -> bool:
        return self.status in (RegionStatus.HEALTHY, RegionStatus.DEGRADED)


class NoRegionAvailable(RuntimeError):
    """No serving region exists for the request (all down/draining)."""


class RegionRegistry:
    """The global view of regions and their health.

    In production this is fed by the global control plane (region inventory) and a
    health pipeline; here it is an in-memory authority with the same interface.
    """

    def __init__(self, regions: list[Region] | None = None) -> None:
        self._regions: dict[str, Region] = {r.id: r for r in (regions or [])}

    def upsert(self, region: Region) -> None:
        self._regions[region.id] = region

    def set_status(self, region_id: str, status: RegionStatus) -> None:
        if region_id in self._regions:
            self._regions[region_id].status = status

    def get(self, region_id: str) -> Region | None:
        return self._regions.get(region_id)

    def all(self) -> list[Region]:
        return list(self._regions.values())

    def serving(self) -> list[Region]:
        return [r for r in self._regions.values() if r.serving]


class RegionRouter:
    """Locality-first, health-aware, active-active routing with failover.

    ``route(locality)`` returns an ordered failover chain of serving regions:
    same-locality first (healthy before degraded, then by descending weight),
    then other localities as spillover. The first element is where to send the
    request; the rest are the active-active failover order.
    """

    def __init__(self, registry: RegionRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _rank(r: Region) -> tuple[int, float]:
        # Healthy outranks degraded; higher weight first (negated for ascending sort).
        status_rank = 0 if r.status is RegionStatus.HEALTHY else 1
        return (status_rank, -r.weight)

    def route(self, locality: str | None = None) -> list[Region]:
        serving = self._registry.serving()
        if not serving:
            raise NoRegionAvailable("no serving region")
        local = sorted((r for r in serving if r.locality == locality), key=self._rank)
        remote = sorted((r for r in serving if r.locality != locality), key=self._rank)
        return local + remote

    def primary(self, locality: str | None = None) -> Region:
        return self.route(locality)[0]

    def failover_after(self, failed_region_id: str, locality: str | None = None) -> Region:
        """The next serving region after one has just failed (active-active)."""
        chain = [r for r in self.route(locality) if r.id != failed_region_id]
        if not chain:
            raise NoRegionAvailable("no failover region available")
        return chain[0]
