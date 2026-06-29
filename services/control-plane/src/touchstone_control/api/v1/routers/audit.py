"""Audit trail read router.

The audit-engine writes a per-organization, hash-chained, tamper-evident log into
``audit_records`` in its **own** database (after the per-service-database split).
This router exposes a read-only, organization-scoped view for the dashboard's
audit trail viewer, reading through the control-plane's read-only audit
connection (``AuditReader``). Records are returned newest-first; each carries its
chain position and the previous/own hash so a client can display chain continuity.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from fastapi import APIRouter, Depends, Request

from ....domain.rbac import Permission, Principal
from ....schemas import AuditRecordOut
from ...v1.deps import require

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditRecordOut], summary="List audit records")
async def list_audit_records(
    request: Request,
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
    limit: int = 100,
) -> list[Mapping[str, object]]:
    reader = request.app.state.audit_reader
    return await reader.list_for_org(uuid.UUID(principal.org_id), limit=limit)
