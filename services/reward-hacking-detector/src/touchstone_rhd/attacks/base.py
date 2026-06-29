"""Attack strategy interface.

An ``AttackStrategy`` turns seed cases (and/or the verifier definition) into a
set of adversarial ``AttackVariant``s. Strategies are intentionally small and
single-purpose so the catalogue is easy to extend and each is independently
testable. ``generate`` is async so model-backed strategies can call a provider;
purely rule-based strategies simply don't await anything.

Reproducibility: a strategy must derive ALL randomness from ``ctx.rng`` (a seeded
``random.Random``). Given the same seed, cases, and verifier definition, it must
emit the same variants — this is what makes whole evaluations deterministically
replayable.
"""

from __future__ import annotations

import random
from typing import Protocol

from ..domain.models import AttackCase, AttackVariant, ExploitCategory
from ..providers import ModelProvider


class AttackContext:
    """Shared, read-only context handed to every strategy during generation."""

    def __init__(
        self,
        *,
        rng: random.Random,
        verifier_definition: dict,
        provider: ModelProvider | None = None,
    ) -> None:
        self.rng = rng
        self.verifier_definition = verifier_definition
        self.provider = provider


class AttackStrategy(Protocol):
    name: str
    category: ExploitCategory

    async def generate(
        self, cases: list[AttackCase], ctx: AttackContext
    ) -> list[AttackVariant]:
        ...
