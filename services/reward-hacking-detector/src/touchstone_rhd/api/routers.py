"""Reward-hacking-detector HTTP API.

Endpoints (all scoped to the caller's organization):

  POST /v1/robustness/evaluations                     launch an evaluation
  GET  /v1/robustness/evaluations/{id}                query one evaluation
  GET  /v1/robustness/evaluations/{id}/report         export a reproducible report
  GET  /v1/robustness/verifiers/{vid}/evaluations     list a verifier's evaluations
  GET  /v1/robustness/verifiers/{vid}/exploits        the exploit corpus
  GET  /v1/robustness/verifiers/{vid}/trend           robustness trend over time
  POST /v1/robustness/compare                          compare two evaluations

Launching schedules the job on a background task; the endpoint returns 202 with
the evaluation id so callers can poll the GET endpoint.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from ..config import get_settings
from ..domain.models import AttackCase
from ..orchestrator import EvaluationConfig
from ..scoring.robustness import RobustnessScorer
from .auth import Principal, PrincipalDep
from .deps import KBDep, RunnerDep
from .schemas import (
    CompareOut,
    CompareRequest,
    ConfidenceIntervalOut,
    EvaluationAccepted,
    EvaluationOut,
    ExploitOut,
    LaunchEvaluationRequest,
    ReportOut,
    TrendOut,
)

router = APIRouter(prefix="/v1/robustness", tags=["robustness"])
_scorer = RobustnessScorer()


def _eval_out(row: dict) -> EvaluationOut:
    ci = None
    if row.get("ci_low") is not None and row.get("ci_high") is not None:
        ci = ConfidenceIntervalOut(low=row["ci_low"], high=row["ci_high"])
    return EvaluationOut(
        id=row["id"], verifier_id=row["verifier_id"],
        verifier_version=row["verifier_version"], status=row["status"],
        seed=row["seed"], total_attacks=row["total_attacks"],
        executed=row["executed"], errored=row["errored"],
        exploits_found=row["exploits_found"],
        robustness_score=row.get("robustness_score"),
        weighted_robustness_score=row.get("weighted_robustness_score"),
        ci=ci, error=row.get("error"),
    )


def _exploit_out(r: dict) -> ExploitOut:
    return ExploitOut(
        signature=r["signature"], verifier_id=r["verifier_id"],
        verifier_version=r.get("verifier_version", 0), category=r["category"],
        strategy=r["strategy"], severity=r["severity"],
        verifier_score=r["verifier_score"], description=r["description"],
        failure_reason=r.get("failure_reason", ""), occurrences=r["occurrences"],
        artifact=r["artifact"],
    )


async def _require_eval(kb, eval_id: uuid.UUID, org_id: uuid.UUID) -> dict:
    row = await kb.get_evaluation(eval_id)
    if row is None or row["organization_id"] != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation not found.")
    return row


@router.post("/evaluations", response_model=EvaluationAccepted,
             status_code=status.HTTP_202_ACCEPTED)
async def launch_evaluation(
    body: LaunchEvaluationRequest,
    background: BackgroundTasks,
    kb: KBDep,
    runner: RunnerDep,
    principal: Principal = PrincipalDep,
) -> EvaluationAccepted:
    info = await kb.get_verifier(body.verifier_id)
    if info is None or info.organization_id != principal.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifier not found.")

    settings = get_settings()
    config = EvaluationConfig(
        seed=body.seed if body.seed is not None else settings.default_seed,
        max_attacks=body.max_attacks or settings.max_attacks,
        max_concurrency=settings.max_concurrency,
        per_attack_timeout_s=settings.per_attack_timeout_s,
        enable_model_attacks=body.enable_model_attacks,
    )
    seed_cases = [
        AttackCase(artifact=c.artifact, should_pass=c.should_pass, label=c.label)
        for c in body.seed_cases
    ]
    eval_id = await runner.launch(body.verifier_id, config=config, seed_cases=seed_cases)
    if eval_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifier not found.")
    background.add_task(
        runner.run, eval_id, body.verifier_id, config=config, seed_cases=seed_cases
    )
    return EvaluationAccepted(evaluation_id=eval_id, status="pending")


@router.get("/evaluations/{eval_id}", response_model=EvaluationOut)
async def get_evaluation(
    eval_id: uuid.UUID, kb: KBDep, principal: Principal = PrincipalDep,
) -> EvaluationOut:
    return _eval_out(await _require_eval(kb, eval_id, principal.organization_id))


@router.get("/verifiers/{verifier_id}/evaluations", response_model=list[EvaluationOut])
async def list_evaluations(
    verifier_id: uuid.UUID, kb: KBDep, principal: Principal = PrincipalDep,
) -> list[EvaluationOut]:
    rows = await kb.list_evaluations(verifier_id)
    return [_eval_out(r) for r in rows if r["organization_id"] == principal.organization_id]


@router.get("/verifiers/{verifier_id}/exploits", response_model=list[ExploitOut])
async def list_exploits(
    verifier_id: uuid.UUID, kb: KBDep, principal: Principal = PrincipalDep,
) -> list[ExploitOut]:
    rows = await kb.list_exploits(verifier_id)
    return [
        _exploit_out(r) for r in rows
        if r["organization_id"] == principal.organization_id
    ]


@router.get("/exploits/search", response_model=list[ExploitOut])
async def search_exploits(
    kb: KBDep,
    principal: Principal = PrincipalDep,
    verifier_id: uuid.UUID | None = None,
    verifier_version: int | None = None,
    category: str | None = None,
    severity: str | None = None,
    strategy: str | None = None,
    min_score: float | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ExploitOut]:
    """Search the organization's exploit corpus. Always tenant-scoped; ``q`` is a
    free-text match over description / failure reason / strategy / category /
    artifact."""
    rows = await kb.search_exploits(
        principal.organization_id, verifier_id=verifier_id,
        verifier_version=verifier_version, category=category, severity=severity,
        strategy=strategy, min_score=min_score, query=q,
        limit=min(limit, 500), offset=max(offset, 0),
    )
    return [_exploit_out(r) for r in rows]


@router.get("/verifiers/{verifier_id}/trend", response_model=TrendOut)
async def trend(
    verifier_id: uuid.UUID, kb: KBDep, principal: Principal = PrincipalDep,
) -> TrendOut:
    info = await kb.get_verifier(verifier_id)
    if info is None or info.organization_id != principal.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Verifier not found.")
    hist = await kb.history(verifier_id)
    series = [h["robustness_score"] for h in hist if h["robustness_score"] is not None]
    return TrendOut(verifier_id=verifier_id, direction=_scorer.trend(series), history=series)


@router.post("/compare", response_model=CompareOut)
async def compare(
    body: CompareRequest, kb: KBDep, principal: Principal = PrincipalDep,
) -> CompareOut:
    a = await _require_eval(kb, body.baseline_evaluation_id, principal.organization_id)
    b = await _require_eval(kb, body.candidate_evaluation_id, principal.organization_id)
    for row in (a, b):
        if row["status"] != "completed":
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Both evaluations must be completed to compare.")
    old = _scorer.score(executed=a["executed"], exploits=a["exploits_found"])
    new = _scorer.score(executed=b["executed"], exploits=b["exploits_found"])
    cmp = _scorer.compare(old, new)
    return CompareOut(
        baseline_robustness=old.robustness, candidate_robustness=new.robustness,
        delta=cmp.delta, is_regression=cmp.is_regression,
        is_improvement=cmp.is_improvement, overlapping_ci=cmp.overlapping_ci,
        detail=cmp.detail,
    )


@router.get("/evaluations/{eval_id}/report", response_model=ReportOut)
async def report(
    eval_id: uuid.UUID, kb: KBDep, principal: Principal = PrincipalDep,
) -> ReportOut:
    row = await _require_eval(kb, eval_id, principal.organization_id)
    exploits_rows = await kb.list_exploits(row["verifier_id"])
    exploits = [
        _exploit_out(r) for r in exploits_rows
        if r["organization_id"] == principal.organization_id
    ]
    counts: dict[str, int] = {}
    for e in exploits:
        counts[e.category] = counts.get(e.category, 0) + 1
    return ReportOut(
        evaluation=_eval_out(row), seed=row["seed"], config=row.get("config") or {},
        category_counts=counts, exploits=exploits,
    )
