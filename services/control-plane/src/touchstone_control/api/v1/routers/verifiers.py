"""Verifier registry router — the core product surface.

Registering a verifier is how a customer tells Touchstone *how to judge* an AI's
output. Verifiers are versioned: re-registering the same ``slug`` mints a new
immutable version rather than mutating history, so audit trails and robustness
scores always reference an exact verifier version.
"""

from __future__ import annotations

import datetime as _dt
import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from touchstone_events import AuditAction

from ....core.errors import NotFoundError
from ....db.models import Project, Verifier
from ....domain.rbac import Permission, Principal
from ....observability.events import publish_control_plane_action
from ....schemas import VerifierCreate, VerifierOut
from ...v1.deps import SessionDep, require

router = APIRouter(prefix="/projects/{project_id}/verifiers", tags=["verifiers"])


async def _assert_project(
    session: AsyncSession, org_id: str, project_id: uuid.UUID
) -> Project:
    project: Project | None = (
        await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organization_id == uuid.UUID(org_id),
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found.")
    return project


@router.post(
    "",
    response_model=VerifierOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a verifier (auto-versioned)",
)
async def create_verifier(
    project_id: uuid.UUID,
    body: VerifierCreate,
    request: Request,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFIER_CREATE)),
) -> Verifier:
    await _assert_project(session, principal.org_id, project_id)
    # Next version for this (project, slug).
    current_max = (
        await session.execute(
            select(func.max(Verifier.version)).where(
                Verifier.project_id == project_id, Verifier.slug == body.slug
            )
        )
    ).scalar()
    row = Verifier(
        organization_id=uuid.UUID(principal.org_id),
        project_id=project_id,
        name=body.name,
        slug=body.slug,
        version=(current_max or 0) + 1,
        verifier_type=body.verifier_type,
        definition=body.definition,
    )
    session.add(row)
    await session.flush()
    await publish_control_plane_action(
        request.app.state.events,
        org_id=uuid.UUID(principal.org_id),
        action=AuditAction.VERIFIER_REGISTERED,
        actor_type="api_key" if principal.is_machine else "user",
        actor_id=principal.subject,
        resource_type="verifier",
        resource_id=str(row.id),
        metadata={"slug": row.slug, "version": row.version,
                  "verifier_type": row.verifier_type.value,
                  "definition": body.definition},
        trace_id=getattr(request.state, "request_id", None),
    )
    return row


@router.get("", response_model=list[VerifierOut], summary="List verifiers in a project")
async def list_verifiers(
    project_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFIER_READ)),
) -> list[Verifier]:
    await _assert_project(session, principal.org_id, project_id)
    rows = (
        await session.execute(
            select(Verifier)
            .where(Verifier.project_id == project_id, Verifier.deleted_at.is_(None))
            .order_by(Verifier.slug, Verifier.version.desc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/{verifier_id}", response_model=VerifierOut, summary="Get a verifier")
async def get_verifier(
    project_id: uuid.UUID,
    verifier_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFIER_READ)),
) -> Verifier:
    row = (
        await session.execute(
            select(Verifier).where(
                Verifier.id == verifier_id,
                Verifier.project_id == project_id,
                Verifier.organization_id == uuid.UUID(principal.org_id),
                Verifier.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Verifier not found.")
    return row


@router.delete(
    "/{verifier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-delete a verifier",
)
async def delete_verifier(
    project_id: uuid.UUID,
    verifier_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.VERIFIER_DELETE)),
) -> Response:
    row = (
        await session.execute(
            select(Verifier).where(
                Verifier.id == verifier_id,
                Verifier.project_id == project_id,
                Verifier.organization_id == uuid.UUID(principal.org_id),
                Verifier.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Verifier not found.")
    row.deleted_at = _dt.datetime.now(_dt.UTC)
    row.is_active = False
    return Response(status_code=status.HTTP_204_NO_CONTENT)
