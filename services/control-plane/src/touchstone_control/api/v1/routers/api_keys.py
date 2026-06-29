"""API key management router.

Security-critical: the plaintext secret is returned in the create response and
**never** again. Listing only ever exposes the public ``key_id``.
"""

from __future__ import annotations

import datetime as _dt
import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from touchstone_events import AuditAction

from ....core.errors import NotFoundError
from ....db.models import ApiKey
from ....domain.rbac import Permission, Principal
from ....observability.events import publish_control_plane_action
from ....schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from ...v1.deps import SecurityDep, SessionDep, require

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description="Generates a new machine credential. The plaintext `secret` is "
    "returned exactly once and is unrecoverable thereafter.",
)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    session: SessionDep,
    security: SecurityDep,
    principal: Principal = Depends(require(Permission.API_KEY_CREATE)),
) -> ApiKeyCreated:
    generated = security.generate_api_key()
    row = ApiKey(
        organization_id=uuid.UUID(principal.org_id),
        project_id=body.project_id,
        name=body.name,
        key_id=generated.key_id,
        secret_hash=generated.secret_hash,
        role=body.role,
        expires_at=body.expires_at,
        created_by=uuid.UUID(principal.user_id) if principal.user_id else None,
    )
    session.add(row)
    await session.flush()
    await publish_control_plane_action(
        request.app.state.events,
        org_id=uuid.UUID(principal.org_id),
        action=AuditAction.API_KEY_CREATED,
        actor_type="api_key" if principal.is_machine else "user",
        actor_id=principal.subject,
        resource_type="api_key",
        resource_id=str(row.id),
        metadata={"name": row.name, "role": row.role.value, "key_id": row.key_id},
        trace_id=getattr(request.state, "request_id", None),
    )
    out = ApiKeyOut.model_validate(row).model_dump()
    return ApiKeyCreated(**out, secret=generated.plaintext)


@router.get("", response_model=list[ApiKeyOut], summary="List API keys")
async def list_api_keys(
    session: SessionDep,
    principal: Principal = Depends(require(Permission.API_KEY_READ)),
) -> list[ApiKey]:
    rows = (
        await session.execute(
            select(ApiKey)
            .where(ApiKey.organization_id == uuid.UUID(principal.org_id))
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    session: SessionDep,
    principal: Principal = Depends(require(Permission.API_KEY_REVOKE)),
) -> Response:
    row = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.organization_id == uuid.UUID(principal.org_id),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("API key not found.")
    if row.revoked_at is None:
        row.revoked_at = _dt.datetime.now(_dt.UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
