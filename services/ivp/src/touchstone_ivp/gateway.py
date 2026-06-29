"""The inline gateway HTTP surface.

* ``POST /v1/inline/verify`` — the hot path: one decision per call.
* ``POST /v1/inline/verify/stream`` — chunk-streamed evaluation with early-exit.
* ``GET/POST /v1/inline/policies`` — manage inline policies for the tenant.

Decision auditing + escalation emission run in the background so the response
returns as soon as the verdict is known.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from .auth import Principal, get_principal
from .policy import PolicyNotFound
from .schemas import Decision, InlineVerifyRequest, Policy, PolicyCreate
from .streaming import StreamSession

router = APIRouter(prefix="/v1/inline", tags=["inline"])

PrincipalDep = Depends(get_principal)


@router.post("/verify", response_model=Decision, summary="Inline-verify one output")
async def verify(
    req: InlineVerifyRequest, request: Request, background: BackgroundTasks,
    principal: Principal = PrincipalDep,
) -> Decision:
    plane = request.app.state.plane
    try:
        result = await plane.verify(principal.organization_id, req)
    except PolicyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    background.add_task(plane.emit, principal.organization_id, result)
    return result.decision


class StreamRequest(BaseModel):
    policy_id: uuid.UUID | None = None
    policy_slug: str | None = None
    chunks: list[str]
    latency_budget_ms: float | None = None
    mode: str = "enforce"


class StreamVerdict(BaseModel):
    seq: int
    action: str
    terminal: bool
    decision: Decision


@router.post("/verify/stream", response_model=list[StreamVerdict],
             summary="Stream-verify chunked output with early-exit")
async def verify_stream(
    req: StreamRequest, request: Request, background: BackgroundTasks,
    principal: Principal = PrincipalDep,
) -> list[StreamVerdict]:
    plane = request.app.state.plane
    session = StreamSession(
        plane, principal.organization_id, policy_id=req.policy_id,
        policy_slug=req.policy_slug, latency_budget_ms=req.latency_budget_ms, mode=req.mode,
    )
    verdicts: list[StreamVerdict] = []
    try:
        for seq, chunk in enumerate(req.chunks):
            result, terminal = await session.push(chunk)
            verdicts.append(StreamVerdict(
                seq=seq, action=result.decision.action.value, terminal=terminal,
                decision=result.decision,
            ))
            # Audit the final/terminal verdict in the background.
            if terminal or seq == len(req.chunks) - 1:
                background.add_task(plane.emit, principal.organization_id, result)
            if terminal:
                break
    except PolicyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return verdicts


@router.get("/policies", response_model=list[Policy], summary="List inline policies")
async def list_policies(request: Request, principal: Principal = PrincipalDep) -> list[Policy]:
    engine = request.app.state.policy_engine
    return engine.store.list(principal.organization_id)


@router.post("/policies", response_model=Policy, status_code=status.HTTP_201_CREATED,
             summary="Create or replace an inline policy")
async def create_policy(
    body: PolicyCreate, request: Request, principal: Principal = PrincipalDep,
) -> Policy:
    engine = request.app.state.policy_engine
    existing = engine.store.list(principal.organization_id)
    epoch = max((p.epoch for p in existing if p.slug == body.slug), default=-1) + 1
    policy = Policy(
        slug=body.slug, org_id=principal.organization_id, project_id=body.project_id,
        verifiers=body.verifiers, thresholds=body.thresholds,
        latency_budget_ms=body.latency_budget_ms, fail_mode=body.fail_mode,
        sampling_rate=body.sampling_rate, min_robustness=body.min_robustness,
        redaction_rules=body.redaction_rules, epoch=epoch,
    )
    stored = engine.store.put(policy)
    # Propagate to other regions via the global control-plane log (if enabled).
    distribution = getattr(request.app.state, "distribution", None)
    if distribution is not None:
        distribution.publish(stored)
    return stored


@router.get("/policies/{policy_id}", response_model=Policy, summary="Get an inline policy")
async def get_policy(
    policy_id: uuid.UUID, request: Request, principal: Principal = PrincipalDep,
) -> Policy:
    engine = request.app.state.policy_engine
    try:
        return await engine.store.get(principal.organization_id, policy_id=policy_id)
    except PolicyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
