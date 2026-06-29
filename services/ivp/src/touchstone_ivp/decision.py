"""The decision engine: turn verifier outcomes into an action.

Pipeline: robustness-weighted aggregation of the fast-tier outcomes → the
risk-engine's transparent risk model → policy thresholds → an action
(allow / block / redact / escalate). Escalation is chosen when the verdict needs
the slow tier (a model/process verifier) or confidence is too low; redaction
applies the policy's regex rules. Every decision carries an explainable
``reasons`` block — inline enforcement must be auditable.
"""

from __future__ import annotations

import re

from touchstone_risk.scorer import RiskModel

from .resilience import fail_action
from .schemas import (
    Action,
    Decision,
    InlineVerifierRef,
    Policy,
    VerifierOutcome,
    sha256,
)

_RISK = RiskModel()


def _aggregate(outcomes: list[VerifierOutcome]) -> tuple[float, float, bool, bool] | None:
    """Weighted (score, uncertainty, passed, any_critical_failed) over scored outcomes.

    Returns None when no verifier produced a score (all errored / none ran).
    """
    scored = [o for o in outcomes if o.score is not None]
    if not scored:
        return None
    total_w = sum(max(o.weight, 0.0) for o in scored) or float(len(scored))
    wscore = sum((o.score or 0.0) * max(o.weight, 0.0) for o in scored) / total_w
    wunc = sum((o.uncertainty or 0.0) * max(o.weight, 0.0) for o in scored) / total_w
    critical_failed = any(o.critical and o.passed is False for o in scored)
    passed = (wscore >= 0.5) and not critical_failed
    return wscore, wunc, passed, critical_failed


def _apply_redaction(content: str, policy: Policy) -> str:
    redacted = content
    for rule in policy.redaction_rules:
        try:
            redacted = re.sub(rule.pattern, rule.replacement, redacted)
        except re.error:
            # A malformed rule must never crash the hot path; skip it.
            continue
    return redacted


class DecisionEngine:
    def __init__(self, risk_model: RiskModel | None = None) -> None:
        self._risk = risk_model or _RISK

    def decide(
        self,
        *,
        content: str,
        policy: Policy,
        outcomes: list[VerifierOutcome],
        escalations: list[InlineVerifierRef],
        routed_around: list,
        fail_mode: str,
        elapsed_ms: float,
        mode: str = "enforce",
    ) -> Decision:
        chash = sha256(content)
        reasons: dict = {
            "policy_id": str(policy.id),
            "routed_around": [str(v) for v in routed_around],
            "fail_mode": fail_mode,
        }
        critical_errored = any(o.error and o.critical for o in outcomes)
        agg = _aggregate(outcomes)

        # 1. Fail-closed on a critical verifier we could not evaluate.
        if critical_errored and str(fail_mode).lower() == "closed":
            return self._terminal(
                Action.BLOCK, content, policy, outcomes, chash, elapsed_ms, mode,
                {**reasons, "cause": "critical_verifier_error"}, risk=1.0, degraded=True,
            )

        # 2. No usable inline signal at all.
        if agg is None:
            if escalations:
                return self._escalate(content, policy, outcomes, escalations, chash,
                                      elapsed_ms, mode, reasons)
            # Nothing ran (all errored or all routed around) — degrade per mode.
            action = fail_action(fail_mode)
            return self._terminal(
                action, content, policy, outcomes, chash, elapsed_ms, mode,
                {**reasons, "cause": "no_inline_signal"},
                risk=(1.0 if action is Action.BLOCK else 0.0), degraded=True,
            )

        wscore, wunc, passed, _ = agg
        assessment = self._risk.assess(score=wscore, uncertainty=wunc, passed=passed)
        risk = assessment.risk_score
        reasons.update({
            "weighted_score": round(wscore, 4),
            "weighted_uncertainty": round(wunc, 4),
            "risk_score": risk,
            "risk_band": assessment.band.value,
            "factors": assessment.factors,
        })
        t = policy.thresholds

        # 3. Block / redact on risk thresholds (block takes precedence).
        if risk >= t.block_at:
            return self._terminal(Action.BLOCK, content, policy, outcomes, chash,
                                  elapsed_ms, mode, {**reasons, "cause": "risk>=block_at"},
                                  risk=risk, band=assessment.band.value)
        if t.redact_at is not None and risk >= t.redact_at:
            return self._terminal(Action.REDACT, content, policy, outcomes, chash,
                                  elapsed_ms, mode, {**reasons, "cause": "risk>=redact_at"},
                                  risk=risk, band=assessment.band.value)

        # 4. Escalate if the slow tier is needed or confidence is too low.
        if escalations or (
            t.escalate_uncertainty_at is not None and wunc >= t.escalate_uncertainty_at
        ):
            return self._escalate(content, policy, outcomes, escalations, chash,
                                  elapsed_ms, mode, {**reasons, "cause": "needs_slow_tier"},
                                  risk=risk, band=assessment.band.value)

        # 5. Allow.
        return self._terminal(Action.ALLOW, content, policy, outcomes, chash,
                              elapsed_ms, mode, {**reasons, "cause": "below_thresholds"},
                              risk=risk, band=assessment.band.value)

    # --- builders -----------------------------------------------------------

    def _terminal(self, action, content, policy, outcomes, chash, elapsed_ms, mode,
                  reasons, *, risk, band="low", degraded=False) -> Decision:
        redacted = _apply_redaction(content, policy) if action is Action.REDACT else None
        return Decision(
            action=action, risk_score=round(risk, 6), risk_band=band, reasons=reasons,
            outcomes=outcomes, latency_ms=round(elapsed_ms, 3), content_sha256=chash,
            mode=mode, redacted_content=redacted, degraded=degraded,
        )

    def _escalate(self, content, policy, outcomes, escalations, chash, elapsed_ms, mode,
                  reasons, *, risk=0.0, band="low") -> Decision:
        return Decision(
            action=Action.ESCALATE, risk_score=round(risk, 6), risk_band=band,
            reasons=reasons, outcomes=outcomes, latency_ms=round(elapsed_ms, 3),
            content_sha256=chash, mode=mode,
            escalation={
                "verifier_ids": [str(r.verifier_id) for r in escalations],
                "note": "deep verdict returns asynchronously via verification.completed",
            },
        )
