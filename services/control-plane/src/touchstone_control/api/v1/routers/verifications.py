"""Verification runtime router.

``POST /verifications`` is the highest-throughput write endpoint. It:
  1. Validates the verifier exists and belongs to the principal's org.
  2. Honors idempotency keys (a retried submit returns the existing run).
  3. Persists a PENDING `VerificationRun`.
  4. Publishes a ``verification.requested`` event for the verification-engine.

The actual grading is asynchronous; clients poll ``GET /verifications/{id}`` or
subscribe to webhooks (V2). This keeps the submit path sub-50ms.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from touchstone_events import VerificationRequestedPayload, new_envelope

from ....core.errors import NotFoundError, PermissionDeniedError
from ....db.models import VerificationRun, VerificationStatus, Verifier
from ....domain.rbac import Permission, Principal
from ....schemas import VerificationOut, VerificationSubmit
from ...v1.deps import SessionDep, require

router = APIRouter(prefix="/verifications", tags=["verifications"])


@router.post(
    "",
    response_model=VerificationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an artifact for verification",
)
async def submit_verification(
    body: VerificationSubmit,
    request: Request,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFICATION_SUBMIT)),
) -> VerificationRun:
    verifier = (
        await session.execute(
            select(Verifier).where(
                Verifier.id == body.verifier_id,
                Verifier.organization_id == uuid.UUID(principal.org_id),
                Verifier.deleted_at.is_(None),
                Verifier.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if verifier is None:
        raise NotFoundError("Verifier not found or inactive.")

    # Project-scoped API keys may only verify within their bound project.
    if principal.project_id and str(verifier.project_id) != principal.project_id:
        raise PermissionDeniedError("API key is not scoped to this verifier's project.")

    # Idempotency: short-circuit a retried submit.
    if body.idempotency_key:
        existing = (
            await session.execute(
                select(VerificationRun).where(
                    VerificationRun.organization_id == uuid.UUID(principal.org_id),
                    VerificationRun.idempotency_key == body.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    run = VerificationRun(
        organization_id=uuid.UUID(principal.org_id),
        project_id=verifier.project_id,
        verifier_id=verifier.id,
        status=VerificationStatus.PENDING,
        artifact_ref=body.artifact_ref,
        idempotency_key=body.idempotency_key,
    )
    session.add(run)
    await session.flush()

    producer = request.app.state.events
    envelope = new_envelope(
        org_id=uuid.UUID(principal.org_id),
        workspace_id=None,
        trace_id=getattr(request.state, "request_id", None),
        idempotency_key=body.idempotency_key or str(run.id),
        payload=VerificationRequestedPayload(
            verification_id=run.id,
            verifier_id=verifier.id,
            project_id=verifier.project_id,
            artifact_ref=body.artifact_ref,
            requested_by=principal.subject,
        ),
    )
    await producer.publish(envelope)
    return run


@router.get("", response_model=list[VerificationOut], summary="List verification runs")
async def list_verifications(
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFICATION_READ)),
    project_id: uuid.UUID | None = None,
    verifier_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[VerificationRun]:
    """List runs for the principal's organization, newest first.

    Optional ``project_id`` / ``verifier_id`` filters narrow the result. A
    project-scoped API key is constrained to its own project regardless of the
    filter, preserving tenant + project isolation.
    """
    stmt = select(VerificationRun).where(
        VerificationRun.organization_id == uuid.UUID(principal.org_id)
    )
    if principal.project_id:
        stmt = stmt.where(VerificationRun.project_id == uuid.UUID(principal.project_id))
    elif project_id is not None:
        stmt = stmt.where(VerificationRun.project_id == project_id)
    if verifier_id is not None:
        stmt = stmt.where(VerificationRun.verifier_id == verifier_id)
    stmt = stmt.order_by(VerificationRun.created_at.desc()).limit(min(limit, 500))
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{verification_id}", response_model=VerificationOut, summary="Get a run")
async def get_verification(
    verification_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFICATION_READ)),
) -> VerificationRun:
    run = (
        await session.execute(
            select(VerificationRun).where(
                VerificationRun.id == verification_id,
                VerificationRun.organization_id == uuid.UUID(principal.org_id),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Verification run not found.")
    return run
