"""Touchstone fleet primitives — multi-region control for the IVP.

The software mechanisms behind a global, multi-region inline plane: a region
registry with health-aware **region-aware routing** and **active-active
failover**; **global policy distribution** by monotonic generation with
observable cross-region convergence; and **fenced-lease coordination** for
single-owner fleet operations.

Honest scope: these are decision/coordination *mechanisms*, built and tested. The
real signals they consume (live health, real cross-region transport, real
partitions) and their behavior under production load are capabilities that only
exist with live multi-region operation.
"""

from .chaos import (
    ChaosRunner,
    ChaosScenario,
    ChaosStep,
    Fault,
    FaultInjector,
    InjectedFault,
)
from .coordination import FencedResource, FencingError, Lease, LeaseHeld
from .distribution import (
    DistributionCoordinator,
    GlobalPolicyLog,
    PolicyRecord,
    RegionalReplica,
)
from .fleet import Worker, WorkerFleet
from .forecast import (
    CapacityPlanner,
    CapacityRecommendation,
    ewma,
    holt_forecast,
)
from .region import (
    NoRegionAvailable,
    Region,
    RegionRegistry,
    RegionRouter,
    RegionStatus,
)
from .scheduler import DistributedScheduler, NoCapacity, Placement
from .slo import SLO, SLOTracker, multi_window_burn_alert
from .store import InMemoryLeaseStore, LeaseStore, run_lease_store_conformance

__all__ = [
    "Region",
    "RegionStatus",
    "RegionRegistry",
    "RegionRouter",
    "NoRegionAvailable",
    "GlobalPolicyLog",
    "PolicyRecord",
    "RegionalReplica",
    "DistributionCoordinator",
    "Lease",
    "LeaseHeld",
    "FencingError",
    "FencedResource",
    "Worker",
    "WorkerFleet",
    "DistributedScheduler",
    "Placement",
    "NoCapacity",
    "FaultInjector",
    "Fault",
    "InjectedFault",
    "ChaosScenario",
    "ChaosStep",
    "ChaosRunner",
    "SLO",
    "SLOTracker",
    "multi_window_burn_alert",
    "ewma",
    "holt_forecast",
    "CapacityPlanner",
    "CapacityRecommendation",
    "LeaseStore",
    "InMemoryLeaseStore",
    "run_lease_store_conformance",
]
