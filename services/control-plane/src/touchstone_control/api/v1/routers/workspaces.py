"""Workspace router. Workspaces partition an org's projects (e.g. by team)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ....core.errors import ConflictError, NotFoundError
from ....db.models import Workspace
from ....domain.rbac import Permission, Principal
from ....schemas import WorkspaceCreate, WorkspaceOut
from ...v1.deps import SessionDep, require

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED,
             summary="Create a workspace")
async def create_workspace(
    body: WorkspaceCreate,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.WORKSPACE_CREATE)),
) -> Workspace:
    row = Workspace(
        organization_id=uuid.UUID(principal.org_id), name=body.name, slug=body.slug
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"Workspace slug '{body.slug}' already exists.") from exc
    return row


@router.get("", response_model=list[WorkspaceOut], summary="List workspaces")
async def list_workspaces(
    session: SessionDep,
    principal: Principal = Depends(require(Permission.WORKSPACE_READ)),
) -> list[Workspace]:
    rows = (
        await session.execute(
            select(Workspace).where(
                Workspace.organization_id == uuid.UUID(principal.org_id),
                Workspace.deleted_at.is_(None),
            ).order_by(Workspace.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/{workspace_id}", response_model=WorkspaceOut, summary="Get a workspace")
async def get_workspace(
    workspace_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.WORKSPACE_READ)),
) -> Workspace:
    row = (
        await session.execute(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == uuid.UUID(principal.org_id),
                Workspace.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Workspace not found.")
    return row
