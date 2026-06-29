"""Authentication router — the platform's front door (public, unauthenticated).

``POST /v1/auth/signup`` bootstraps a brand-new tenant: it creates the user, the
organization, and an OWNER membership binding them, then returns a JWT scoped to
that org. The three inserts happen in one transaction, so a duplicate email or
org slug rolls the whole thing back — we never leave a half-created user or org.

``POST /v1/auth/login`` validates credentials and returns a JWT. Login is
constant-time with respect to email existence (a dummy hash verify runs when the
email is unknown) to avoid user enumeration, and all credential failures return
the same generic 401.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from touchstone_events import AuditAction

from ....core.errors import AuthenticationError, ConflictError, ValidationError
from ....db.models import Membership, Organization, User
from ....domain.rbac import Role
from ....observability.events import publish_control_plane_action
from ....schemas import LoginRequest, SignupRequest, TokenPair
from ...v1.deps import SecurityDep, SessionDep, SettingsDep

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(security, settings, *, user_id, org: Organization) -> TokenPair:
    access = security.issue_access_token(user_id=user_id, org_id=org.id)
    return TokenPair(
        access_token=access,
        expires_in=settings.jwt_access_ttl_seconds,
        org_id=org.id,
        org_slug=org.slug,
    )


@router.post(
    "/signup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user + organization and return a JWT",
)
async def signup(
    body: SignupRequest,
    request: Request,
    session: SessionDep,
    security: SecurityDep,
    settings: SettingsDep,
) -> TokenPair:
    email = body.email.lower()

    # Friendly pre-checks (the unique constraints below are the race-safe backstop).
    if (
        await session.execute(select(User.id).where(User.email == email))
    ).scalar_one_or_none() is not None:
        raise ConflictError("An account with this email already exists.", field="email")
    if (
        await session.execute(select(Organization.id).where(Organization.slug == body.org_slug))
    ).scalar_one_or_none() is not None:
        raise ConflictError(
            "This organization slug is already taken.", field="org_slug"
        )

    user = User(
        email=email,
        full_name=body.full_name,
        password_hash=security.hash_password(body.password),
        is_active=True,
    )
    org = Organization(name=body.org_name, slug=body.org_slug, settings={})
    session.add_all([user, org])
    try:
        await session.flush()
        session.add(
            Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER)
        )
        await session.flush()
    except IntegrityError as exc:  # backstop against a race on the unique columns
        raise ConflictError("Email or organization slug already exists.") from exc

    await publish_control_plane_action(
        request.app.state.events,
        org_id=org.id,
        action=AuditAction.USER_SIGNUP,
        actor_type="user",
        actor_id=str(user.id),
        resource_type="organization",
        resource_id=str(org.id),
        metadata={"email": email, "org_slug": org.slug},
        trace_id=getattr(request.state, "request_id", None),
    )
    return _token_pair(security, settings, user_id=user.id, org=org)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Validate credentials and return a JWT",
)
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    security: SecurityDep,
    settings: SettingsDep,
) -> TokenPair:
    email = body.email.lower()
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    # Constant-time: always perform a verify so timing doesn't reveal existence.
    if user is None or user.password_hash is None:
        security.dummy_verify()
        raise AuthenticationError("Invalid email or password.")
    if not security.verify_password(body.password, user.password_hash):
        raise AuthenticationError("Invalid email or password.")
    if not user.is_active:
        raise AuthenticationError("This account is disabled.")

    # Resolve which organization the token is scoped to.
    memberships = (
        await session.execute(
            select(Membership, Organization)
            .join(Organization, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id, Organization.deleted_at.is_(None))
        )
    ).all()
    if not memberships:
        raise AuthenticationError("This user does not belong to any organization.")

    if body.org_slug is not None:
        match = next((o for _, o in memberships if o.slug == body.org_slug), None)
        if match is None:
            raise AuthenticationError("User is not a member of that organization.")
        org = match
    elif len(memberships) == 1:
        org = memberships[0][1]
    else:
        raise ValidationError(
            "User belongs to multiple organizations; specify 'org_slug'.",
            organizations=[o.slug for _, o in memberships],
        )

    await publish_control_plane_action(
        request.app.state.events,
        org_id=org.id,
        action=AuditAction.USER_LOGIN,
        actor_type="user",
        actor_id=str(user.id),
        resource_type="organization",
        resource_id=str(org.id),
        metadata={"email": email},
        trace_id=getattr(request.state, "request_id", None),
    )
    return _token_pair(security, settings, user_id=user.id, org=org)
