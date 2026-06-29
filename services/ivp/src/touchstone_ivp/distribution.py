"""Global policy distribution for the IVP.

Wires the plane's policy resolution to the global control plane: a policy created
in any region is published to a global, generation-ordered log; every region's
plane resolves policies from its local :class:`RegionalReplica`, which pulls the
log and converges — no synchronous dependency on the center on the hot path. This
is what makes a policy authored in ``us-east-1`` resolvable in ``eu-west-1``.

The plane's local ``PolicyStore`` is the fast same-region cache; this distributor
is its ``loader`` — consulted on a miss, it pulls the replica and reconstructs the
policy. The distribution *logic* is exercised here; real cross-region transport is
the M2 production capability the seam is built for.
"""

from __future__ import annotations

import uuid

from touchstone_fleet import DistributionCoordinator, GlobalPolicyLog, RegionalReplica

from .schemas import Policy


class GlobalPolicyDistribution:
    def __init__(self, region_id: str, *, log: GlobalPolicyLog | None = None) -> None:
        self.log = log or GlobalPolicyLog()
        self.replica = RegionalReplica(region_id)
        self.coordinator = DistributionCoordinator(self.log)
        self.coordinator.register(self.replica)

    def publish(self, policy: Policy) -> None:
        """Publish a policy version to the global log (propagates to all regions)."""
        self.log.publish(
            policy_id=str(policy.id), org_id=str(policy.org_id), epoch=policy.epoch,
            payload=policy.model_dump(mode="json"),
        )

    def retire(self, policy: Policy) -> None:
        self.log.retire(policy_id=str(policy.id), org_id=str(policy.org_id),
                        epoch=policy.epoch)

    async def loader(
        self, org_id: uuid.UUID, policy_id: uuid.UUID | None = None,
        policy_slug: str | None = None,
    ) -> Policy | None:
        """PolicyStore loader: pull the replica, then resolve by id or slug."""
        self.replica.pull(self.log)
        record = None
        if policy_id is not None:
            record = self.replica.get(str(policy_id))
        elif policy_slug is not None:
            for rec in self.replica.records():
                if rec.payload.get("slug") == policy_slug and rec.org_id == str(org_id):
                    record = rec
                    break
        if record is None or record.org_id != str(org_id):
            return None
        return Policy.model_validate(record.payload)

    def converged(self) -> bool:
        return self.coordinator.converged()
