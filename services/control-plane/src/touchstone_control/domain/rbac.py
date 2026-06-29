"""Role-Based Access Control (ADR-010).

Authorization is enforced at three nested scopes:

    Organization  ->  Workspace  ->  Project

A principal (a user, via membership, or an API key, via its bound scopes) is
granted a **role** at a scope. Roles expand to a fixed set of **permissions**.
The `Authorizer` answers a single question: *may this principal perform this
permission on this resource?* — and nothing else. Keeping the decision pure and
centralized makes it auditable and unit-testable in isolation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Permission(str, enum.Enum):
    # Organization administration
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    ORG_DELETE = "org:delete"
    ORG_MEMBER_MANAGE = "org:member:manage"
    ORG_BILLING_MANAGE = "org:billing:manage"

    # Workspaces
    WORKSPACE_CREATE = "workspace:create"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"

    # API keys
    API_KEY_CREATE = "api_key:create"
    API_KEY_READ = "api_key:read"
    API_KEY_REVOKE = "api_key:revoke"

    # Projects
    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"

    # Verifiers (the core product registry)
    VERIFIER_CREATE = "verifier:create"
    VERIFIER_READ = "verifier:read"
    VERIFIER_UPDATE = "verifier:update"
    VERIFIER_DELETE = "verifier:delete"

    # Verification runtime (used by SDK/API)
    VERIFICATION_SUBMIT = "verification:submit"
    VERIFICATION_READ = "verification:read"

    # Audit
    AUDIT_READ = "audit:read"


class Role(str, enum.Enum):
    """Org-level roles. Ordered loosely from most to least privileged."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    # Machine principal role for API keys with full project read/write but no
    # org administration. The default role minted with a new key.
    SERVICE = "service"


_ALL: frozenset[Permission] = frozenset(Permission)

_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.ORG_READ,
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.VERIFIER_READ,
        Permission.VERIFICATION_READ,
        Permission.AUDIT_READ,
        Permission.API_KEY_READ,
    }
)

_MEMBER: frozenset[Permission] = _VIEWER | frozenset(
    {
        Permission.WORKSPACE_CREATE,
        Permission.WORKSPACE_UPDATE,
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.VERIFIER_CREATE,
        Permission.VERIFIER_UPDATE,
        Permission.VERIFICATION_SUBMIT,
        Permission.API_KEY_CREATE,
    }
)

_SERVICE: frozenset[Permission] = frozenset(
    {
        Permission.PROJECT_READ,
        Permission.VERIFIER_READ,
        Permission.VERIFICATION_SUBMIT,
        Permission.VERIFICATION_READ,
    }
)

_ADMIN: frozenset[Permission] = _MEMBER | frozenset(
    {
        Permission.ORG_UPDATE,
        Permission.ORG_MEMBER_MANAGE,
        Permission.WORKSPACE_DELETE,
        Permission.PROJECT_DELETE,
        Permission.VERIFIER_DELETE,
        Permission.API_KEY_REVOKE,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ADMIN,
    Role.MEMBER: _MEMBER,
    Role.VIEWER: _VIEWER,
    Role.SERVICE: _SERVICE,
}


@dataclass(frozen=True)
class Principal:
    """The authenticated actor for a request.

    Exactly one of (user_id, api_key_id) identifies the principal; both carry
    the org scope and an effective role.
    """

    org_id: str
    role: Role
    user_id: str | None = None
    api_key_id: str | None = None
    # For API keys we may further restrict to a single project.
    project_id: str | None = None

    @property
    def is_machine(self) -> bool:
        return self.api_key_id is not None

    @property
    def subject(self) -> str:
        return self.user_id or self.api_key_id or "anonymous"


class Authorizer:
    """Pure authorization decisions. No I/O, fully unit-testable."""

    @staticmethod
    def permissions_for(role: Role) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[role]

    @classmethod
    def can(cls, principal: Principal, permission: Permission) -> bool:
        return permission in cls.permissions_for(principal.role)

    @classmethod
    def can_in_org(cls, principal: Principal, permission: Permission, org_id: str) -> bool:
        """Tenancy gate: the principal must belong to the org being acted upon."""
        if principal.org_id != org_id:
            return False
        return cls.can(principal, permission)
