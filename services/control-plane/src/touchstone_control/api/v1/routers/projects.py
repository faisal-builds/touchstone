"""Project router. Projects live under a workspace and own verifiers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ....core.errors import ConflictError, NotFoundError
from ....db.models import Project, Workspace
from ....domain.rbac import Permission, Principal
from ....schemas import ProjectCreate, ProjectOut
from ...v1.deps import SessionDep, require

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])


async def _assert_workspace(session, org_id: str, workspace_id: uuid.UUID) -> Workspace:
    ws = (
        await session.execute(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == uuid.UUID(org_id),
                Workspace.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if ws is None:
        raise NotFoundError("Workspace not found.")
    return ws


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED,
             summary="Create a project")
async def create_project(
    workspace_id: uuid.UUID,
    body: ProjectCreate,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.PROJECT_CREATE)),
) -> Project:
    await _assert_workspace(session, principal.org_id, workspace_id)
    row = Project(
        organization_id=uuid.UUID(principal.org_id),
        workspace_id=workspace_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(f"Project slug '{body.slug}' already exists.") from exc
    return row


@router.get("", response_model=list[ProjectOut], summary="List projects")
async def list_projects(
    workspace_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.PROJECT_READ)),
) -> list[Project]:
    await _assert_workspace(session, principal.org_id, workspace_id)
    rows = (
        await session.execute(
            select(Project).where(
                Project.workspace_id == workspace_id,
                Project.deleted_at.is_(None),
            ).order_by(Project.created_at.desc())
        )
    ).scalars().all()
    return list(rows)
