"""Authentication for the RHD API.

Two credential types are accepted:

  * a machine API key (``tsk_<keyid>_<secret>``), validated by calling the
    control-plane's introspection endpoint (auth federation) rather than reading
    the shared ``api_keys`` table — so the RHD never touches the control-plane
    database and can run on a fully isolated database;
  * a user JWT issued by the control-plane, verified with the shared secret.

The resolved organization id scopes every query, so a caller can only ever see
its own evaluations and exploits (multi-tenant isolation). Machine API keys are
the right credential for robustness evaluations (they run in CI / pipelines); the
dashboard uses the JWT.
"""

from __future__ import annotations

import dataclasses
import uuid

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from ..config import get_settings


@dataclasses.dataclass(frozen=True, slots=True)
class Principal:
    organization_id: uuid.UUID
    key_id: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


async def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token.")
    token = authorization[7:].strip()
    if token.startswith("tsk_"):
        return await _principal_from_api_key(request, token)
    return _principal_from_jwt(token)


def _principal_from_jwt(token: str) -> Principal:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token.") from exc
    org = claims.get("org")
    if not org:
        raise _unauthorized("Token is missing an organization claim.")
    try:
        org_id = uuid.UUID(str(org))
    except ValueError as exc:
        raise _unauthorized("Token organization claim is malformed.") from exc
    return Principal(organization_id=org_id, key_id=f"jwt:{claims.get('sub', '')}")


async def _principal_from_api_key(request: Request, token: str) -> Principal:
    # Shape check only; the secret is never inspected here — the control-plane
    # validates it via introspection (RHD holds no key material).
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "tsk":
        raise _unauthorized("Malformed API key.")
    introspector = request.app.state.introspector
    principal = await introspector.introspect(token)
    if principal is None:
        raise _unauthorized("Invalid API key.")
    return principal


PrincipalDep = Depends(get_principal)
