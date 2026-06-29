"""Worker fleet + distributed scheduler: heartbeats, placement, spill, backpressure."""

from __future__ import annotations

import pytest

from touchstone_fleet import (
    DistributedScheduler,
    NoCapacity,
    Region,
    RegionRegistry,
    RegionRouter,
    Worker,
    WorkerFleet,
)


def _router() -> RegionRouter:
    return RegionRouter(RegionRegistry([
        Region("us-east-1", "na"), Region("eu-west-1", "eu"),
    ]))


def test_heartbeat_ttl_prunes_dead_workers():
    clock = {"t": 0.0}
    fleet = WorkerFleet(heartbeat_ttl_s=10.0, clock=lambda: clock["t"])
    fleet.register(Worker("w1", "us-east-1"))
    clock["t"] = 5.0
    fleet.register(Worker("w2", "us-east-1"))
    clock["t"] = 12.0  # w1 (hb@0) dead, w2 (hb@5) alive
    pruned = fleet.prune_dead()
    assert pruned == ["w1"]
    assert {w.id for w in fleet.all()} == {"w2"}


def test_scheduler_places_in_local_region():
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1"))
    fleet.register(Worker("eu1", "eu-west-1"))
    sched = DistributedScheduler(fleet, _router())
    p = sched.place(locality="na")
    assert p.region == "us-east-1"
    assert p.spilled is False


def test_scheduler_picks_least_loaded():
    fleet = WorkerFleet()
    busy = Worker("na1", "us-east-1", capacity=8, in_flight=6)
    idle = Worker("na2", "us-east-1", capacity=8, in_flight=1)
    fleet.register(busy)
    fleet.register(idle)
    sched = DistributedScheduler(fleet, _router())
    assert sched.place(locality="na").worker_id == "na2"


def test_scheduler_spills_to_remote_when_local_full():
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1", capacity=1, in_flight=1))  # no capacity
    fleet.register(Worker("eu1", "eu-west-1"))
    sched = DistributedScheduler(fleet, _router())
    p = sched.place(locality="na")
    assert p.region == "eu-west-1"
    assert p.spilled is True


def test_assign_and_complete_track_in_flight():
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1", capacity=4))
    sched = DistributedScheduler(fleet, _router())
    sched.assign(locality="na")
    assert fleet.all()[0].in_flight == 1
    sched.complete("na1")
    assert fleet.all()[0].in_flight == 0


def test_backpressure_when_no_capacity_anywhere():
    fleet = WorkerFleet()
    fleet.register(Worker("na1", "us-east-1", capacity=1, in_flight=1))
    fleet.register(Worker("eu1", "eu-west-1", capacity=1, in_flight=1))
    sched = DistributedScheduler(fleet, _router())
    with pytest.raises(NoCapacity):
        sched.place(locality="na")


def test_draining_worker_is_not_scheduled():
    fleet = WorkerFleet()
    w = Worker("na1", "us-east-1")
    fleet.register(w)
    fleet.set_draining("na1", True)
    fleet.register(Worker("eu1", "eu-west-1"))
    sched = DistributedScheduler(fleet, _router())
    assert sched.place(locality="na").region == "eu-west-1"
