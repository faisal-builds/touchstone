"""Correctness-breaking mutation attacks (category: CONTENT_CORRUPTION).

Takes seed cases that *should pass* and corrupts their substantive content so the
true label flips to *should fail* — then checks whether the verifier still passes.
A verifier that does is not actually checking correctness; it is gameable.

Mutations are type-aware (dict / list / str / scalar) and all randomness comes
from the seeded RNG, so the same seed reproduces the same corruptions.
"""

from __future__ import annotations

import copy
from typing import Any

from ..domain.models import AttackCase, AttackVariant, ExploitCategory
from .base import AttackContext


class MutationAttack:
    name = "content_mutation"
    category = ExploitCategory.CONTENT_CORRUPTION

    async def generate(
        self, cases: list[AttackCase], ctx: AttackContext
    ) -> list[AttackVariant]:
        variants: list[AttackVariant] = []
        for case in cases:
            if not case.should_pass:
                continue  # we corrupt things that currently deserve to pass
            for mutated, desc in self._mutate(case.artifact, ctx):
                variants.append(
                    AttackVariant(
                        artifact=mutated,
                        strategy=self.name,
                        category=self.category,
                        expected_pass=False,  # correctness is now broken
                        description=desc,
                    )
                )
        return variants

    def _mutate(self, artifact: Any, ctx: AttackContext):
        out = []
        if isinstance(artifact, dict) and artifact:
            keys = sorted(artifact.keys())
            # 1. Corrupt a numeric/string value (break the answer).
            k = keys[ctx.rng.randrange(len(keys))]
            corrupted = copy.deepcopy(artifact)
            corrupted[k] = self._corrupt_value(artifact[k], ctx)
            out.append((corrupted, f"corrupted value of field '{k}'"))
            # 2. Drop a required key entirely.
            dropped = copy.deepcopy(artifact)
            dk = keys[ctx.rng.randrange(len(keys))]
            dropped.pop(dk, None)
            out.append((dropped, f"removed field '{dk}'"))
            # 3. Null out a field.
            nulled = copy.deepcopy(artifact)
            nk = keys[ctx.rng.randrange(len(keys))]
            nulled[nk] = None
            out.append((nulled, f"nulled field '{nk}'"))
        elif isinstance(artifact, list) and artifact:
            # Drop a step (break a trajectory).
            dropped = list(artifact)
            del dropped[ctx.rng.randrange(len(dropped))]
            out.append((dropped, "removed a trajectory step"))
            out.append(([], "emptied the trajectory"))
        elif isinstance(artifact, str):
            out.append(("", "replaced content with empty string"))
            out.append((artifact[: max(1, len(artifact) // 4)], "truncated content"))
            out.append(("TODO", "replaced content with a stub"))
        else:
            out.append((None, "replaced artifact with null"))
        return out

    @staticmethod
    def _corrupt_value(value: Any, ctx: AttackContext) -> Any:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return value + ctx.rng.choice([-1, 1, 7, -42, 1000])
        if isinstance(value, str):
            return "" if value else "wrong"
        if isinstance(value, list):
            return []
        return None
