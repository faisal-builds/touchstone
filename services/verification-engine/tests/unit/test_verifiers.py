"""Unit tests for each verifier family and the ensemble meta-verification logic."""

import pytest

from touchstone_verify.engine.base import VerifierContext, VerifierError
from touchstone_verify.engine.code_verifier import CodeVerifier
from touchstone_verify.engine.ensemble import EnsembleVerifier
from touchstone_verify.engine.model_verifier import ModelVerifier
from touchstone_verify.engine.process_verifier import ProcessVerifier
from touchstone_verify.providers.mock import MockProvider
from touchstone_verify.sandbox.runner import SandboxLimits, SandboxRunner

CTX = VerifierContext(verification_id="v1", verifier_id="vf1")


@pytest.fixture
def sandbox():
    return SandboxRunner(SandboxLimits(cpu_seconds=2, wall_timeout_s=5))


# --- Code verifier --------------------------------------------------------- #
@pytest.mark.asyncio
async def test_code_verifier_pass(sandbox):
    v = CodeVerifier(
        {"code": "def check(a):\n return {'score': 1.0 if a['x']==1 else 0.0}"}, sandbox
    )
    r = await v.verify({"x": 1}, CTX)
    assert r.score == 1.0 and r.passed and r.uncertainty == 0.0


@pytest.mark.asyncio
async def test_code_verifier_fail(sandbox):
    v = CodeVerifier(
        {"code": "def check(a):\n return {'score': 0.0}", "threshold": 1.0}, sandbox
    )
    r = await v.verify({"x": 2}, CTX)
    assert r.score == 0.0 and not r.passed


@pytest.mark.asyncio
async def test_code_verifier_sandbox_failure_raises(sandbox):
    v = CodeVerifier({"code": "def check(a):\n raise RuntimeError('x')"}, sandbox)
    with pytest.raises(VerifierError):
        await v.verify(None, CTX)


def test_code_verifier_requires_code():
    with pytest.raises(VerifierError):
        CodeVerifier({})


# --- Model verifier -------------------------------------------------------- #
@pytest.mark.asyncio
async def test_model_verifier_parses_forced_score():
    v = ModelVerifier(
        {"rubric": "score it __force_score__=0.8", "threshold": 0.5}, MockProvider()
    )
    r = await v.verify("artifact", CTX)
    assert r.score == pytest.approx(0.8) and r.passed


@pytest.mark.asyncio
async def test_model_verifier_self_consistency_uncertainty():
    # Deterministic mock -> identical samples -> zero disagreement uncertainty.
    v = ModelVerifier(
        {"rubric": "judge __force_score__=0.6", "samples": 3}, MockProvider()
    )
    r = await v.verify("a", CTX)
    assert r.uncertainty == 0.0


# --- Process verifier ------------------------------------------------------ #
@pytest.mark.asyncio
async def test_process_verifier_all_pass(sandbox):
    v = ProcessVerifier(
        {"step_code": "def check_step(step, i):\n return {'score': 1.0}"}, sandbox
    )
    r = await v.verify([{"a": 1}, {"a": 2}, {"a": 3}], CTX)
    assert r.score == 1.0 and r.passed
    assert r.details["first_failure_index"] is None


@pytest.mark.asyncio
async def test_process_verifier_localizes_first_failure(sandbox):
    code = "def check_step(step, i):\n return {'score': 0.0 if i==1 else 1.0}"
    v = ProcessVerifier({"step_code": code, "aggregation": "min"}, sandbox)
    r = await v.verify([{}, {}, {}], CTX)
    assert r.score == 0.0
    assert r.details["first_failure_index"] == 1


# --- Ensemble meta-verification -------------------------------------------- #
class _Stub:
    """A stub verifier returning a fixed result, for ensemble logic tests."""
    from touchstone_verify.engine.base import VerifierFamily
    family = VerifierFamily.CODE

    def __init__(self, score, uncertainty=0.0):
        self._s, self._u = score, uncertainty

    async def verify(self, artifact, ctx):
        from touchstone_verify.engine.base import VerificationResult
        return VerificationResult(self._s, self._u, self._s >= 0.5, {"stub": self._s})


@pytest.mark.asyncio
async def test_ensemble_agreement_is_confident():
    ens = EnsembleVerifier([_Stub(0.9), _Stub(0.95), _Stub(0.92)])
    r = await ens.verify(None, CTX)
    assert r.passed
    assert r.uncertainty < 0.1  # graders agree


@pytest.mark.asyncio
async def test_ensemble_disagreement_escalates():
    # One grader says great, one says terrible -> high dispersion -> escalate.
    ens = EnsembleVerifier([_Stub(1.0), _Stub(0.0)], escalate_uncertainty=0.3)
    r = await ens.verify(None, CTX)
    assert r.uncertainty > 0.3
    assert not r.passed  # escalated despite mean == 0.5
    assert r.details["escalated"] is True


@pytest.mark.asyncio
async def test_ensemble_weighted_mean():
    ens = EnsembleVerifier([_Stub(1.0), _Stub(0.0)], weights=[3.0, 1.0])
    r = await ens.verify(None, CTX)
    assert r.score == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_ensemble_tolerates_member_failure():
    class _Boom:
        from touchstone_verify.engine.base import VerifierFamily
        family = VerifierFamily.MODEL
        async def verify(self, a, c):
            raise RuntimeError("provider down")
    ens = EnsembleVerifier([_Stub(0.9), _Boom()])
    r = await ens.verify(None, CTX)
    # Survives, but the failure raises uncertainty.
    assert r.details["members_errored"] == 1
    assert r.uncertainty >= 0.5
