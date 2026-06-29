"""Region registry, region-aware routing, active-active failover."""

from __future__ import annotations

import pytest

from touchstone_fleet import (
    NoRegionAvailable,
    Region,
    RegionRegistry,
    RegionRouter,
    RegionStatus,
)


def _registry() -> RegionRegistry:
    return RegionRegistry([
        Region("us-east-1", "na", weight=2.0),
        Region("us-west-2", "na", weight=1.0),
        Region("eu-west-1", "eu", weight=1.0),
        Region("ap-south-1", "apac", weight=1.0),
    ])


def test_routes_to_local_region_first_by_weight():
    router = RegionRouter(_registry())
    chain = router.route("na")
    assert chain[0].id == "us-east-1"   # local, highest weight
    assert chain[1].id == "us-west-2"   # local, lower weight
    assert {r.id for r in chain[2:]} == {"eu-west-1", "ap-south-1"}  # remote spillover


def test_degraded_region_is_deprioritized_below_healthy():
    reg = _registry()
    reg.set_status("us-east-1", RegionStatus.DEGRADED)
    chain = RegionRouter(reg).route("na")
    assert chain[0].id == "us-west-2"   # healthy local beats degraded local
    assert chain[1].id == "us-east-1"


def test_down_and_draining_regions_are_not_served():
    reg = _registry()
    reg.set_status("us-east-1", RegionStatus.DOWN)
    reg.set_status("us-west-2", RegionStatus.DRAINING)
    chain = RegionRouter(reg).route("na")
    # No NA region serving -> spill to remote.
    assert all(r.locality != "na" for r in chain)


def test_active_active_failover_picks_next_region():
    router = RegionRouter(_registry())
    nxt = router.failover_after("us-east-1", "na")
    assert nxt.id == "us-west-2"


def test_no_region_available_raises():
    reg = RegionRegistry([Region("x", "na", status=RegionStatus.DOWN)])
    with pytest.raises(NoRegionAvailable):
        RegionRouter(reg).route("na")
