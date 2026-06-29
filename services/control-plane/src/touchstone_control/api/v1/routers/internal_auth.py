"""Internal auth introspection (service-to-service).

After the per-service-database split, other services (the reward-hacking-detector)
must not read the control-plane's ``api_keys`` table directly. Instead they call
this endpoint to validate a presented ``tsk_`` API key, so the control-plane
remains the single owner of key material (no Argon2 secret hashes are ever
replicated to another service's database).

The endpoint is internal: it requires a short-lived service token (not a public
credential) and is not exposed through the public ingress. The response follows
the shape of RFC 7662 token introspection — a 200 with ``active: false`` rather
than a 401 for an invalid key, so callers cannot use status codes as an oracle.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from ....core.errors import AuthenticationError
from ..deps import SecurityDep, ServiceTokenDep, SessionDep, SettingsDep, _principal_from_api_key

router = APIRouter(prefix="/internal/auth", tags=["internal"])


class IntrospectRequest(BaseModel):
    api_key: str


class IntrospectResponse(BaseModel):
    active: bool
    organization_id: uuid.UUID | None = None
    key_id: str | None = None
    api_key_id: str | None = None


@router.post("/introspect", response_model=IntrospectResponse, summary="Validate an API key")
async def introspect(
    body: IntrospectRequest,
    session: SessionDep,
    security: SecurityDep,
    settings: SettingsDep,
    _service: ServiceTokenDep,
) -> IntrospectResponse:
    try:
        principal = await _principal_from_api_key(body.api_key, session, security, settings)
    except AuthenticationError:
        return IntrospectResponse(active=False)
    if principal is None or principal.api_key_id is None:
        # Not an API key, or no key identity resolved.
        return IntrospectResponse(active=False)
    parsed = security.parse_api_key(body.api_key)
    key_id = parsed[0] if parsed else None
    return IntrospectResponse(
        active=True,
        organization_id=uuid.UUID(principal.org_id),
        key_id=key_id,
        api_key_id=principal.api_key_id,
    )
