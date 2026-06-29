"""Dependency injection + authentication/authorization wiring.

This module turns an inbound HTTP request into an authenticated, authorized
`Principal`. It supports both auth planes:

  * ``Authorization: Bearer tsk_...``  -> API key auth (machine)
  * ``Authorization: Bearer <jwt>``    -> dashboard session (human)

The `require(permission)` factory produces a dependency that enforces RBAC,
returning 403 as an RFC-7807 problem if the principal lacks the permission.
"""

from __future__ import annotations

import datetime as _dt
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import Settings, get_settings
from ...core.errors import AuthenticationError, PermissionDeniedError
from ...core.security import SecurityService
from ...db.base import Database
from ...db.models import ApiKey, Membership
from ...domain.rbac import Authorizer, Permission, Principal, Role

# These singletons are bound at app startup (see app.py::create_app).
_database: Database | None = None
_security: SecurityService | None = None


def bind_runtime(database: Database, security: SecurityService) -> None:
    global _database, _security
    _database = database
    _security = security


def get_db() -> Database:
    assert _database is not None, "Database not bound; call bind_runtime() at startup"
    return _database


def get_security() -> SecurityService:
    assert _security is not None, "SecurityService not bound"
    return _security


async def get_session(
    db: Annotated[Database, Depends(get_db)],
):
    async for session in db.session():
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SecurityDep = Annotated[SecurityService, Depends(get_security)]


async def require_service_token(request: Request, security: SecurityDep) -> str:
    """Authenticate an internal service-to-service caller.

    Internal endpoints (e.g. auth introspection) are not part of the public API;
    they require a short-lived ``type == "service"`` token signed with the shared
    secret. Returns the calling service name (the ``sub`` claim).
    """
    token = _extract_bearer(request)
    try:
        claims = security.decode_token(token)
    except Exception as exc:  # invalid signature / expired
        raise AuthenticationError("Invalid or expired service token.") from exc
    if claims.get("type") != "service":
        raise AuthenticationError("A service token is required for this endpoint.")
    return str(claims.get("sub", ""))


ServiceTokenDep = Annotated[str, Depends(require_service_token)]


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Missing or malformed Authorization header.")
    return token.strip()


async def _principal_from_api_key(
    token: str, session: AsyncSession, security: SecurityService, settings: Settings
) -> Principal | None:
    parsed = security.parse_api_key(token)
    if parsed is None:
        return None  # not an API key; caller will try JWT
    key_id, secret = parsed
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_id == key_id))
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationError("Invalid API key.")
    if row.revoked_at is not None:
        raise AuthenticationError("API key has been revoked.")
    if row.expires_at is not None and row.expires_at < _dt.datetime.now(_dt.UTC):
        raise AuthenticationError("API key has expired.")
    if not security.verify_api_key_secret(secret, row.secret_hash):
        raise AuthenticationError("Invalid API key.")

    # Transparent hash upgrade if Argon2 params were strengthened.
    if security.needs_rehash(row.secret_hash):
        row.secret_hash = security.rehash_secret(secret)
    row.last_used_at = _dt.datetime.now(_dt.UTC)

    return Principal(
        org_id=str(row.organization_id),
        role=row.role,
        api_key_id=str(row.id),
        project_id=str(row.project_id) if row.project_id else None,
    )


async def _principal_from_jwt(
    token: str, session: AsyncSession, security: SecurityService
) -> Principal:
    try:
        claims = security.decode_token(token)
    except Exception as exc:  # invalid signature/expired
        raise AuthenticationError("Invalid or expired session token.") from exc
    if claims.get("type") != "access":
        raise AuthenticationError("Wrong token type.")
    user_id = claims["sub"]
    org_id = claims["org"]
    membership = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise PermissionDeniedError("User is not a member of this organization.")
    return Principal(org_id=org_id, role=membership.role, user_id=user_id)


async def get_principal(
    request: Request,
    session: SessionDep,
    security: SecurityDep,
    settings: SettingsDep,
) -> Principal:
    token = _extract_bearer(request)
    principal = await _principal_from_api_key(token, session, security, settings)
    if principal is None:
        principal = await _principal_from_jwt(token, session, security)
    # Stash on request state for logging/audit middleware.
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(permission: Permission):
    """Dependency factory enforcing a single RBAC permission."""

    async def _guard(principal: PrincipalDep) -> Principal:
        if not Authorizer.can(principal, permission):
            raise PermissionDeniedError(
                f"Principal lacks required permission: {permission.value}",
                required_permission=permission.value,
                role=principal.role.value,
            )
        return principal

    return _guard


# Convenience: an owner/admin-only guard for org-administration routes.
async def require_org_admin(principal: PrincipalDep) -> Principal:
    if principal.role not in (Role.OWNER, Role.ADMIN):
        raise PermissionDeniedError("Organization admin role required.")
    return principal
