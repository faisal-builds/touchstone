"""Edge-case attacks (category: EDGE_CASE).

Generates degenerate artifacts from scratch — empty, null, extreme, malformed,
and tricky-unicode inputs — none of which deserve to pass. These probe whether a
verifier has a default-accept path, mishandles missing data, or can be derailed
by unusual encodings. Independent of seed cases, so a verifier can be probed even
with no seed material.
"""

from __future__ import annotations

from ..domain.models import AttackVariant, ExploitCategory
from .base import AttackContext

# (artifact, description) pairs. All are undeserving of a pass.
_EDGE_CASES = [
    ("", "empty string"),
    ({}, "empty object"),
    (None, "null artifact"),
    ([], "empty list"),
    ({"answer": None}, "answer is null"),
    ({"answer": ""}, "answer is empty"),
    ("\u200b\u200b\u200b", "zero-width spaces only"),
    ("０", "full-width homoglyph digit"),
    ({"answer": "a" * 100_000}, "pathologically long answer"),
    ({"answer": float("inf")} if False else {"answer": 1e308}, "extreme numeric value"),
    ("\x00\x01\x02", "control characters"),
    ({"__proto__": {"admin": True}}, "prototype-pollution-style keys"),
]


class EdgeCaseAttack:
    name = "edge_cases"
    category = ExploitCategory.EDGE_CASE

    async def generate(self, cases, ctx: AttackContext) -> list[AttackVariant]:
        return [
            AttackVariant(
                artifact=artifact, strategy=self.name, category=self.category,
                description=desc,
            )
            for artifact, desc in _EDGE_CASES
        ]
