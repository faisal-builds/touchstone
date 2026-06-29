"""Exploit-detection unit tests: classification, severity, and dedup signatures."""

from touchstone_rhd.detection.detector import ExploitDetector
from touchstone_rhd.domain.models import (
    AttackOutcome,
    AttackVariant,
    ExploitCategory,
    Severity,
)

D = ExploitDetector()


def _variant(artifact, *, strategy="s", category=ExploitCategory.LENGTH_BIAS, ordinal=0):
    return AttackVariant(artifact=artifact, strategy=strategy, category=category,
                         expected_pass=False, ordinal=ordinal)


def _outcome(artifact, *, passed, score, errored=False, **kw):
    return AttackOutcome(
        variant=_variant(artifact, **kw), verifier_passed=passed,
        verifier_score=score, verifier_uncertainty=0.0, errored=errored,
    )


def test_passing_undeserving_variant_is_exploit():
    assert _outcome({"a": 1}, passed=True, score=1.0).is_exploit


def test_rejected_variant_is_not_exploit():
    assert not _outcome({"a": 1}, passed=False, score=0.0).is_exploit


def test_errored_variant_is_never_exploit():
    assert not _outcome({"a": 1}, passed=True, score=1.0, errored=True).is_exploit


def test_detect_returns_only_exploits():
    outcomes = [
        _outcome({"a": 1}, passed=True, score=1.0, ordinal=0),   # exploit
        _outcome({"a": 2}, passed=False, score=0.1, ordinal=1),  # rejected
    ]
    exploits = D.detect(outcomes)
    assert len(exploits) == 1


def test_severity_scales_with_score():
    assert D.severity(0.95) == Severity.CRITICAL
    assert D.severity(0.8) == Severity.HIGH
    assert D.severity(0.65) == Severity.MEDIUM
    assert D.severity(0.5) == Severity.LOW


def test_similar_exploits_share_signature():
    # Same class of attack, different incidental length -> same signature -> dedup.
    short = _outcome("garbage " + "x" * 60, passed=True, score=1.0, ordinal=0)
    long = _outcome("garbage " + "x" * 90, passed=True, score=1.0, ordinal=1)
    assert D.signature(short) == D.signature(long)
    assert len(D.detect([short, long])) == 1


def test_different_categories_differ_in_signature():
    a = _outcome({"answer": ""}, passed=True, score=1.0,
                 category=ExploitCategory.EDGE_CASE)
    b = _outcome({"answer": ""}, passed=True, score=1.0,
                 category=ExploitCategory.JUDGE_MANIPULATION)
    assert D.signature(a) != D.signature(b)


def test_exploits_sorted_worst_first():
    outcomes = [
        _outcome({"x": "low"}, passed=True, score=0.55, ordinal=0,
                 category=ExploitCategory.EDGE_CASE),
        _outcome({"x": "crit"}, passed=True, score=1.0, ordinal=1,
                 category=ExploitCategory.JUDGE_MANIPULATION),
    ]
    exploits = D.detect(outcomes)
    assert exploits[0].severity == Severity.CRITICAL


def test_exploit_records_why_the_verifier_failed():
    outcome = AttackOutcome(
        variant=_variant({"answer": ""}, strategy="content_mutation",
                         category=ExploitCategory.CONTENT_CORRUPTION),
        verifier_passed=True, verifier_score=1.0, verifier_uncertainty=0.0,
        verifier_breakdown={"code": 1.0},
        verifier_details={"reasoning": "field present, accepted"},
    )
    exploit = D.detect([outcome])[0]
    assert exploit.failure_reason  # non-empty
    # The reason grounds itself in the verifier's own score and breakdown.
    assert "1.00" in exploit.failure_reason
    assert "code=1.00" in exploit.failure_reason
    assert "correctness" in exploit.failure_reason.lower()
