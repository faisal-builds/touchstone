"""Attack generator — composes strategies into one reproducible attack stream.

Determinism is the contract: ``generate(seed)`` with the same strategies, seed
cases, and verifier definition always yields the exact same ordered list of
variants. To keep strategies independent (adding one must not perturb another's
output), each strategy gets its **own** RNG derived from ``seed`` and the
strategy name. Variants are then concatenated in a fixed strategy order and
assigned monotonic ordinals — that ordinal IS the replay coordinate.
"""

from __future__ import annotations

import hashlib
import random

from ..domain.models import AttackCase, AttackVariant
from ..providers import ModelProvider
from .base import AttackContext, AttackStrategy
from .edgecase import EdgeCaseAttack
from .injection import FormattingAttack, InjectionAttack, LengthBiasAttack
from .model_attack import ModelGeneratedAttack
from .mutation import MutationAttack


def default_strategies(*, include_model: bool = True) -> list[AttackStrategy]:
    """The built-in attack catalogue, in a fixed, stable order."""
    strategies: list[AttackStrategy] = [
        MutationAttack(),
        InjectionAttack(),
        LengthBiasAttack(),
        FormattingAttack(),
        EdgeCaseAttack(),
    ]
    if include_model:
        strategies.append(ModelGeneratedAttack())
    return strategies


def _derive_seed(base_seed: int, name: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class AttackGenerator:
    def __init__(
        self,
        strategies: list[AttackStrategy],
        *,
        verifier_definition: dict,
        provider: ModelProvider | None = None,
    ) -> None:
        # Strategy order is fixed (sorted by name) so ordinals are stable.
        self._strategies = sorted(strategies, key=lambda s: s.name)
        self._definition = verifier_definition
        self._provider = provider

    async def generate(
        self, *, seed: int, cases: list[AttackCase], max_attacks: int | None = None
    ) -> list[AttackVariant]:
        variants: list[AttackVariant] = []
        for strategy in self._strategies:
            ctx = AttackContext(
                rng=random.Random(_derive_seed(seed, strategy.name)),
                verifier_definition=self._definition,
                provider=self._provider,
            )
            produced = await strategy.generate(cases, ctx)
            variants.extend(produced)

        # Assign stable ordinals in generation order.
        ordered = [
            AttackVariant(
                artifact=v.artifact, strategy=v.strategy, category=v.category,
                expected_pass=v.expected_pass, description=v.description, ordinal=i,
            )
            for i, v in enumerate(variants)
        ]
        if max_attacks is not None and len(ordered) > max_attacks:
            # Deterministic subsample preserving ordinals.
            rng = random.Random(seed)
            ordered = sorted(rng.sample(ordered, max_attacks), key=lambda v: v.ordinal)
        return ordered
