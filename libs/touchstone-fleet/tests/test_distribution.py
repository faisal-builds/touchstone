"""Global policy distribution + fenced-lease coordination."""

from __future__ import annotations

import pytest

from touchstone_fleet import (
    DistributionCoordinator,
    FencedResource,
    FencingError,
    GlobalPolicyLog,
    Lease,
    LeaseHeld,
    RegionalReplica,
)


def test_replica_pulls_and_converges():
    log = GlobalPolicyLog()
    log.publish(policy_id="p1", org_id="o", epoch=0, payload={"v": 1})
    log.publish(policy_id="p2", org_id="o", epoch=0, payload={"v": 1})

    replica = RegionalReplica("us-east-1")
    applied = replica.pull(log)
    assert applied == 2
    assert replica.get("p1").payload == {"v": 1}
    assert replica.applied_generation == log.generation


def test_last_writer_wins_on_repeated_pull():
    log = GlobalPolicyLog()
    log.publish(policy_id="p1", org_id="o", epoch=0, payload={"v": 1})
    replica = RegionalReplica("r")
    replica.pull(log)
    log.publish(policy_id="p1", org_id="o", epoch=1, payload={"v": 2})
    applied = replica.pull(log)
    assert applied == 1
    assert replica.get("p1").payload == {"v": 2}
    assert replica.get("p1").epoch == 1


def test_retire_removes_policy_from_replica():
    log = GlobalPolicyLog()
    log.publish(policy_id="p1", org_id="o", epoch=0, payload={"v": 1})
    replica = RegionalReplica("r")
    replica.pull(log)
    log.retire(policy_id="p1", org_id="o", epoch=2)
    replica.pull(log)
    assert replica.get("p1") is None


def test_coordinator_tracks_lag_and_convergence():
    log = GlobalPolicyLog()
    coord = DistributionCoordinator(log)
    east, west = RegionalReplica("east"), RegionalReplica("west")
    coord.register(east)
    coord.register(west)

    log.publish(policy_id="p1", org_id="o", epoch=0, payload={})
    assert coord.converged() is False
    assert coord.lag()["east"] == 1

    coord.propagate()
    assert coord.converged() is True
    assert coord.lag() == {"east": 0, "west": 0}


def test_lease_single_owner_and_takeover_after_expiry():
    clock = {"t": 0.0}
    lease = Lease("rollout", ttl_s=10.0, clock=lambda: clock["t"])
    t1 = lease.acquire("node-a")
    assert lease.owner == "node-a"
    with pytest.raises(LeaseHeld):
        lease.acquire("node-b")
    # After TTL, node-b can take over and gets a higher fencing token.
    clock["t"] = 11.0
    t2 = lease.acquire("node-b")
    assert t2 > t1
    assert lease.owner == "node-b"


def test_fenced_resource_rejects_stale_token():
    res = FencedResource()
    applied = []
    res.write(2, lambda: applied.append("new"))
    with pytest.raises(FencingError):
        res.write(1, lambda: applied.append("stale"))  # old leaseholder's late write
    assert applied == ["new"]
