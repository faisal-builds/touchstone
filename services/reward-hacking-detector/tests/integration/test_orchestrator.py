"""Orchestrator integration test (real sandbox execution).

The core correctness property of the detector: it must distinguish a *gameable*
verifier from a *robust* one. We evaluate two code verifiers against the same
attacks:

  * WEAK  — passes anything that merely has an ``answer`` field, ignoring its
            value. Many correctness-breaking and injection attacks keep the field
            present, so the verifier is fooled repeatedly → low robustness.
  * STRONG— passes only when ``answer == 42``. Attacks that break the answer are
            correctly rejected → high robustness, few/no exploits.

Also asserts deterministic replay: the same seed yields the same robustness.
"""

from __future__ import annotations

import pytest

from touchstone_rhd.domain.models import AttackCase
from touchstone_rhd.orchestrator import EvaluationConfig, Orchestrator

WEAK = {
    "type": "code",
    "code": (
        "def check(artifact):\n"
        "    ok = isinstance(artifact, dict) and 'answer' in artifact\n"
        "    return {'score': 1.0 if ok else 0.0}\n"
    ),
    "threshold": 1.0,
}

STRONG = {
    "type": "code",
    "code": (
        "def check(artifact):\n"
        "    ok = isinstance(artifact, dict) and artifact.get('answer') == 42\n"
        "    return {'score': 1.0 if ok else 0.0}\n"
    ),
    "threshold": 1.0,
}

SEED_CASES = [
    AttackCase(artifact={"answer": 42, "explanation": "the meaning"}, should_pass=True),
    AttackCase(artifact={"answer": 0}, should_pass=False, label="wrong"),
]

CONFIG = EvaluationConfig(seed=2024, max_attacks=60, max_concurrency=12,
                          per_attack_timeout_s=10.0, enable_model_attacks=False)


@pytest.mark.asyncio
async def test_weak_verifier_is_less_robust_than_strong():
    orch = Orchestrator()
    weak = await orch.evaluate(verifier_definition=WEAK, seed_cases=SEED_CASES,
                               config=CONFIG, evaluation_id="weak")
    strong = await orch.evaluate(verifier_definition=STRONG, seed_cases=SEED_CASES,
                                 config=CONFIG, evaluation_id="strong")

    # The weak verifier is fooled; the strong one resists.
    assert weak.exploits_found > 0
    assert weak.robustness_score < strong.robustness_score
    assert strong.robustness_score >= 0.9
    # Weak verifier exploits span multiple attack categories.
    assert len(weak.category_counts) >= 2
    # Confidence interval is well-formed.
    assert 0.0 <= weak.robustness_ci.low <= weak.robustness_ci.high <= 1.0


@pytest.mark.asyncio
async def test_evaluation_is_reproducible():
    orch = Orchestrator()
    a = await orch.evaluate(verifier_definition=WEAK, seed_cases=SEED_CASES,
                            config=CONFIG, evaluation_id="r1")
    b = await orch.evaluate(verifier_definition=WEAK, seed_cases=SEED_CASES,
                            config=CONFIG, evaluation_id="r2")
    assert a.total_attacks == b.total_attacks
    assert a.robustness_score == b.robustness_score
    assert {e.signature for e in a.exploits} == {e.signature for e in b.exploits}


@pytest.mark.asyncio
async def test_hostile_artifacts_are_handled_safely():
    """Edge-case attacks (null bytes, huge inputs) must never crash the run;
    they are recorded as errors or rejections, not exploits or exceptions."""
    orch = Orchestrator()
    result = await orch.evaluate(verifier_definition=STRONG, seed_cases=SEED_CASES,
                                 config=CONFIG, evaluation_id="hostile")
    assert result.total_attacks > 0
    assert result.executed + result.errored == result.total_attacks
