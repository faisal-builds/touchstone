"""Policy resolution and robustness-aware verifier selection.

The policy engine answers two questions for every inline call: *which policy
applies* and *which verifiers in it can be trusted inline right now*. The second
is Touchstone's differentiator — verifiers whose robustness score (from the RHD)
falls below the policy's floor are **routed around**, because putting a known-
gameable grader in the critical path is worse than not checking at all. Live RHD
scores (fed by ``robustness_evaluated`` events) override the score embedded in the
policy at publish time.

``PolicyStore`` is an in-memory, epoch-versioned cache. In production its
``loader`` is wired to the control-plane (the source of truth for tenant config);
here it is populated directly, which is all the plane needs to run and be tested.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from .schemas import InlineVerifierRef, Policy


class PolicyNotFound(Exception):
    pass


class RobustnessCache:
    """Live verifier robustness scores, fed by the RHD ``robustness_evaluated``
    event stream. Read on the hot path to weight / gate verifiers."""

    def __init__(self) -> None:
        self._scores: dict[uuid.UUID, float] = {}

    def set(self, verifier_id: uuid.UUID, score: float) -> None:
        self._scores[verifier_id] = max(0.0, min(1.0, score))

    def get(self, verifier_id: uuid.UUID) -> float | None:
        return self._scores.get(verifier_id)


PolicyLoader = Callable[[uuid.UUID, uuid.UUID | None, str | None], Awaitable[Policy | None]]


class PolicyStore:
    """Epoch-versioned in-memory policy cache.

    Keyed by (org_id, policy_id) and (org_id, slug). A ``loader`` (optional) is the
    production hook to fetch/refresh from the control-plane; a cache miss falls
    through to it once.
    """

    def __init__(self, loader: PolicyLoader | None = None) -> None:
        self._by_id: dict[tuple[uuid.UUID, uuid.UUID], Policy] = {}
        self._by_slug: dict[tuple[uuid.UUID, str], Policy] = {}
        self._loader = loader

    def put(self, policy: Policy) -> Policy:
        self._by_id[(policy.org_id, policy.id)] = policy
        self._by_slug[(policy.org_id, policy.slug)] = policy
        return policy

    def list(self, org_id: uuid.UUID) -> list[Policy]:
        return [p for (o, _), p in self._by_id.items() if o == org_id]

    async def get(
        self, org_id: uuid.UUID, *, policy_id: uuid.UUID | None = None,
        policy_slug: str | None = None,
    ) -> Policy:
        if policy_id is not None:
            hit = self._by_id.get((org_id, policy_id))
        elif policy_slug is not None:
            hit = self._by_slug.get((org_id, policy_slug))
        else:
            raise PolicyNotFound("policy_id or policy_slug is required")
        if hit is not None:
            return hit
        if self._loader is not None:
            loaded = await self._loader(org_id, policy_id, policy_slug)
            if loaded is not None:
                return self.put(loaded)
        raise PolicyNotFound("no such policy for this organization")


class PolicyEngine:
    def __init__(self, store: PolicyStore, robustness: RobustnessCache | None = None) -> None:
        self._store = store
        self._robustness = robustness or RobustnessCache()

    @property
    def store(self) -> PolicyStore:
        return self._store

    @property
    def robustness(self) -> RobustnessCache:
        return self._robustness

    async def resolve(
        self, org_id: uuid.UUID, *, policy_id: uuid.UUID | None = None,
        policy_slug: str | None = None,
    ) -> Policy:
        return await self._store.get(org_id, policy_id=policy_id, policy_slug=policy_slug)

    def effective_robustness(self, ref: InlineVerifierRef) -> float | None:
        """Live RHD score if known, else the score embedded at publish time."""
        live = self._robustness.get(ref.verifier_id)
        return live if live is not None else ref.robustness_score

    def select(
        self, policy: Policy
    ) -> tuple[list[tuple[InlineVerifierRef, float]], list[uuid.UUID]]:
        """Return (selected [(ref, weight)], routed_around [verifier_id]).

        A verifier is routed around when its effective robustness is known and
        below ``policy.min_robustness``. Selected verifiers are weighted by their
        robustness (unknown => weight 1.0, trusted by default but flagged).
        """
        selected: list[tuple[InlineVerifierRef, float]] = []
        routed_around: list[uuid.UUID] = []
        for ref in policy.verifiers:
            r = self.effective_robustness(ref)
            if policy.min_robustness is not None and r is not None and r < policy.min_robustness:
                routed_around.append(ref.verifier_id)
                continue
            weight = r if r is not None else 1.0
            selected.append((ref, weight))
        return selected, routed_around
