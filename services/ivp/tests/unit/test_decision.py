"""Decision engine: aggregation, action mapping, redaction, fail-closed."""

from __future__ import annotations

import uuid

from touchstone_ivp.decision import DecisionEngine
from touchstone_ivp.schemas import (
    Action,
    ActionThresholds,
    InlineVerifierRef,
    Policy,
    RedactionRule,
    Tier,
    VerifierOutcome,
)

ORG = uuid.uuid4()
PROJ = uuid.uuid4()
ENGINE = DecisionEngine()


def _policy(**kw) -> Policy:
    return Policy(slug="p", org_id=ORG, project_id=PROJ, **kw)


def _outcome(score, passed, *, weight=1.0, critical=False, error=None) -> VerifierOutcome:
    return VerifierOutcome(
        verifier_id=uuid.uuid4(), tier=Tier.FAST, score=score, uncertainty=0.0,
        passed=passed, weight=weight, critical=critical, error=error,
    )


def _decide(policy, outcomes, *, escalations=None, fail_mode="open"):
    return ENGINE.decide(
        content="hello world", policy=policy, outcomes=outcomes,
        escalations=escalations or [], routed_around=[], fail_mode=fail_mode,
        elapsed_ms=1.0,
    )


def test_allow_when_passing_and_low_risk():
    d = _decide(_policy(), [_outcome(1.0, True)])
    assert d.action is Action.ALLOW
    assert d.risk_score < 0.25


def test_block_when_risk_exceeds_block_threshold():
    policy = _policy(thresholds=ActionThresholds(block_at=0.5))
    d = _decide(policy, [_outcome(0.0, False)])  # failing => risk ~0.6
    assert d.action is Action.BLOCK


def test_redact_applies_rules():
    policy = _policy(
        thresholds=ActionThresholds(block_at=0.9, redact_at=0.5),
        redaction_rules=[RedactionRule(pattern=r"world", replacement="[X]")],
    )
    d = _decide(policy, [_outcome(0.0, False)])
    assert d.action is Action.REDACT
    assert d.redacted_content == "hello [X]"


def test_escalate_when_slow_verifier_required():
    policy = _policy(thresholds=ActionThresholds(block_at=0.99))
    slow = InlineVerifierRef(verifier_id=uuid.uuid4(), tier=Tier.SLOW)
    d = _decide(policy, [_outcome(0.9, True)], escalations=[slow])
    assert d.action is Action.ESCALATE
    assert d.escalation and str(slow.verifier_id) in d.escalation["verifier_ids"]


def test_robustness_weighting_lets_trusted_verifier_dominate():
    # Trusted verifier (w=0.9) fails; flaky one (w=0.1) passes -> aggregate fails.
    outcomes = [_outcome(0.0, False, weight=0.9), _outcome(1.0, True, weight=0.1)]
    policy = _policy(thresholds=ActionThresholds(block_at=0.5))
    d = _decide(policy, outcomes)
    assert d.action is Action.BLOCK
    assert d.reasons["weighted_score"] < 0.2


def test_fail_closed_on_critical_verifier_error():
    policy = _policy()
    bad = _outcome(None, None, critical=True, error="sandbox failure")
    d = _decide(policy, [bad], fail_mode="closed")
    assert d.action is Action.BLOCK
    assert d.degraded is True
    assert d.reasons["cause"] == "critical_verifier_error"


def test_no_signal_fails_open_when_configured():
    policy = _policy()
    bad = _outcome(None, None, error="boom")
    d = _decide(policy, [bad], fail_mode="open")
    assert d.action is Action.ALLOW
    assert d.degraded is True
