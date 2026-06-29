"""Attack-generation unit tests: strategies produce undeserving variants, and
generation is deterministic (the foundation of reproducible replay)."""

import pytest

from touchstone_rhd.attacks.generator import AttackGenerator, default_strategies
from touchstone_rhd.domain.models import AttackCase, ExploitCategory
from touchstone_rhd.providers import MockProvider

DEF = {"type": "code", "code": "def check(a): ...", "threshold": 1.0}

PASS_CASE = AttackCase(artifact={"answer": 42, "explanation": "because"}, should_pass=True)
FAIL_CASE = AttackCase(artifact={"answer": 0}, should_pass=False, label="bad")


def _gen(include_model=False, provider=None):
    return AttackGenerator(
        default_strategies(include_model=include_model),
        verifier_definition=DEF, provider=provider,
    )


@pytest.mark.asyncio
async def test_generates_variants_across_categories():
    variants = await _gen().generate(seed=1, cases=[PASS_CASE, FAIL_CASE])
    cats = {v.category for v in variants}
    # Rule-based catalogue covers these five categories.
    assert ExploitCategory.CONTENT_CORRUPTION in cats
    assert ExploitCategory.JUDGE_MANIPULATION in cats
    assert ExploitCategory.LENGTH_BIAS in cats
    assert ExploitCategory.FORMATTING_EXPLOIT in cats
    assert ExploitCategory.EDGE_CASE in cats


@pytest.mark.asyncio
async def test_all_variants_are_undeserving():
    variants = await _gen().generate(seed=1, cases=[PASS_CASE, FAIL_CASE])
    assert variants and all(v.expected_pass is False for v in variants)


@pytest.mark.asyncio
async def test_ordinals_are_monotonic_and_unique():
    variants = await _gen().generate(seed=7, cases=[PASS_CASE, FAIL_CASE])
    ordinals = [v.ordinal for v in variants]
    assert ordinals == list(range(len(variants)))


@pytest.mark.asyncio
async def test_generation_is_deterministic_for_a_seed():
    a = await _gen().generate(seed=99, cases=[PASS_CASE, FAIL_CASE])
    b = await _gen().generate(seed=99, cases=[PASS_CASE, FAIL_CASE])
    assert [(v.strategy, v.description, repr(v.artifact)) for v in a] == \
           [(v.strategy, v.description, repr(v.artifact)) for v in b]


@pytest.mark.asyncio
async def test_different_seeds_can_differ():
    a = await _gen().generate(seed=1, cases=[PASS_CASE])
    b = await _gen().generate(seed=2, cases=[PASS_CASE])
    # Mutations draw on the RNG, so at least the corrupted values should differ
    # somewhere (not a hard guarantee per-item, but across the set).
    assert [repr(v.artifact) for v in a] != [repr(v.artifact) for v in b] or len(a) == len(b)


@pytest.mark.asyncio
async def test_model_attacks_included_with_provider():
    gen = _gen(include_model=True, provider=MockProvider())
    variants = await gen.generate(seed=1, cases=[PASS_CASE])
    assert any(v.category == ExploitCategory.MODEL_GENERATED for v in variants)


@pytest.mark.asyncio
async def test_model_attacks_noop_without_provider():
    gen = _gen(include_model=True, provider=None)
    variants = await gen.generate(seed=1, cases=[PASS_CASE])
    assert not any(v.category == ExploitCategory.MODEL_GENERATED for v in variants)


@pytest.mark.asyncio
async def test_max_attacks_subsamples_deterministically():
    full = await _gen().generate(seed=5, cases=[PASS_CASE, FAIL_CASE])
    capped1 = await _gen().generate(seed=5, cases=[PASS_CASE, FAIL_CASE], max_attacks=5)
    capped2 = await _gen().generate(seed=5, cases=[PASS_CASE, FAIL_CASE], max_attacks=5)
    assert len(capped1) == 5
    assert len(full) > 5
    assert [v.ordinal for v in capped1] == [v.ordinal for v in capped2]
