"""Game-day: compose region routing, scheduler, chaos, and SLO end to end.

Drives a small fleet through a simulated regional outage and asserts the system
behaves correctly: work spills to the surviving region, the failed region stops
receiving placements, and the SLO/error-budget reflects the dropped requests.
This exercises the *composition* of the milestone-1 primitives (the mechanism);
it is not a production reliability result.
"""

from __future__ import annotations

from touchstone_fleet import (
    SLO,
    ChaosRunner,
    ChaosScenario,
    ChaosStep,
    DistributedScheduler,
    FaultInjector,
    InjectedFault,
    NoCapacity,
    Region,
    RegionRegistry,
    RegionRouter,
    RegionStatus,
    SLOTracker,
    Worker,
    WorkerFleet,
)


async def test_regional_outage_spills_and_burns_budget():
    # Two regions, one worker each.
    registry = RegionRegistry([Region("us-east-1", "na"), Region("eu-west-1", "eu")])
    router = RegionRouter(registry)
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1", capacity=4))
    fleet.register(Worker("eu1", "eu-west-1", capacity=4))
    sched = DistributedScheduler(fleet, router)
    injector = FaultInjector()
    slo = SLOTracker(SLO("inline", objective=0.99))

    async def probe() -> str:
        # One "request" from an NA caller: chaos may fail the local region.
        try:
            injector.failpoint("region.us-east-1")
        except InjectedFault:
            registry.set_status("us-east-1", RegionStatus.DOWN)
        try:
            placement = sched.assign(locality="na")
            slo.record(good=True)
            return placement.region
        except NoCapacity:
            slo.record(good=False)
            return "shed"

    scenario = ChaosScenario("na region outage", [
        ChaosStep("healthy"),                                  # -> us-east-1
        ChaosStep("kill-na", arm={"name": "region.us-east-1", "error": True}),  # -> eu spill
        ChaosStep("still-down"),                               # -> eu (na marked DOWN)
    ])
    results = [r for _, r in await ChaosRunner(injector).run(scenario, probe)]

    assert results[0] == "us-east-1"      # served locally while healthy
    assert results[1] == "eu-west-1"      # failover spill after the injected outage
    assert results[2] == "eu-west-1"      # na stays out until it recovers
    # All three were served (none shed) -> SLO fully attained this round.
    assert slo.attainment() == 1.0


async def test_capacity_exhaustion_sheds_and_dents_budget():
    registry = RegionRegistry([Region("us-east-1", "na")])
    router = RegionRouter(registry)
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1", capacity=1))
    sched = DistributedScheduler(fleet, router)
    slo = SLOTracker(SLO("inline", objective=0.99))

    # First assign fills the only slot; the second has nowhere to go -> shed.
    sched.assign(locality="na")
    slo.record(good=True)
    try:
        sched.assign(locality="na")
        slo.record(good=True)
    except NoCapacity:
        slo.record(good=False)

    assert slo.attainment() == 0.5
    assert slo.error_budget_remaining() < 0   # budget blown by the shed request
