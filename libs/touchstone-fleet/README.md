# touchstone-fleet

Multi-region fleet primitives for the Touchstone Inline Verification Plane — the
software mechanisms behind a global, enterprise-grade inline platform. Built and
tested in isolation; **not production-proven** (see the honest-scope note below).

| Concern | Module | Key types |
|---|---|---|
| Region routing + active-active failover | `region.py` | `RegionRegistry`, `RegionRouter`, `RegionStatus` |
| Global policy distribution + convergence | `distribution.py` | `GlobalPolicyLog`, `RegionalReplica`, `DistributionCoordinator` |
| Distributed state coordination | `coordination.py` | `Lease` (fenced), `FencedResource` |
| Worker fleet + scheduler | `fleet.py`, `scheduler.py` | `WorkerFleet`, `DistributedScheduler` |
| Chaos engineering | `chaos.py` | `FaultInjector`, `ChaosScenario`, `ChaosRunner` |
| SLOs + error budgets | `slo.py` | `SLO`, `SLOTracker`, `multi_window_burn_alert` |
| Capacity forecasting | `forecast.py` | `holt_forecast`, `CapacityPlanner` |

```python
from touchstone_fleet import RegionRegistry, Region, RegionRouter, WorkerFleet, \
    Worker, DistributedScheduler

router = RegionRouter(RegionRegistry([Region("us-east-1", "na"), Region("eu-west-1", "eu")]))
fleet = WorkerFleet(); fleet.register(Worker("na1", "us-east-1"))
sched = DistributedScheduler(fleet, router)
placement = sched.assign(locality="na")   # least-loaded, region-aware, with failover
```

The IVP consumes these via `touchstone_ivp.enterprise.EnterpriseContext` (region
stamping, SLO recording, chaos failpoints) and exposes `GET /v1/ops/status`.

## Tests

```bash
cd libs/touchstone-fleet && PYTHONPATH=src pytest -q   # 32 tests, incl. a game-day
```

## Honest scope

These are decision/coordination **mechanisms**. The real signals they consume
(live health, real cross-region transport, real partitions, real demand) and their
behavior under production load are capabilities that only exist with live
multi-region operation. This library makes those experiments and that operation
*possible*; it does not substitute for having run them.
