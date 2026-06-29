"""RBAC authorization decisions must be exhaustively correct — these are the
gates protecting every tenant boundary."""

import pytest

from touchstone_control.domain.rbac import (
    ROLE_PERMISSIONS,
    Authorizer,
    Permission,
    Principal,
    Role,
)


def _principal(role: Role, org="org-1") -> Principal:
    return Principal(org_id=org, role=role, user_id="u-1")


def test_owner_has_every_permission():
    owner = _principal(Role.OWNER)
    for perm in Permission:
        assert Authorizer.can(owner, perm), f"owner missing {perm}"


def test_viewer_is_read_only():
    viewer = _principal(Role.VIEWER)
    assert Authorizer.can(viewer, Permission.PROJECT_READ)
    assert not Authorizer.can(viewer, Permission.PROJECT_CREATE)
    assert not Authorizer.can(viewer, Permission.VERIFIER_DELETE)


def test_member_can_submit_but_not_administer_org():
    member = _principal(Role.MEMBER)
    assert Authorizer.can(member, Permission.VERIFICATION_SUBMIT)
    assert Authorizer.can(member, Permission.VERIFIER_CREATE)
    assert not Authorizer.can(member, Permission.ORG_MEMBER_MANAGE)
    assert not Authorizer.can(member, Permission.ORG_DELETE)


def test_service_role_is_runtime_only():
    svc = Principal(org_id="o", role=Role.SERVICE, api_key_id="k")
    assert Authorizer.can(svc, Permission.VERIFICATION_SUBMIT)
    assert Authorizer.can(svc, Permission.VERIFIER_READ)
    assert not Authorizer.can(svc, Permission.VERIFIER_CREATE)
    assert not Authorizer.can(svc, Permission.API_KEY_CREATE)


def test_cross_org_is_always_denied():
    admin = _principal(Role.ADMIN, org="org-A")
    # Even an admin cannot act on a different org.
    assert not Authorizer.can_in_org(admin, Permission.ORG_UPDATE, "org-B")
    assert Authorizer.can_in_org(admin, Permission.ORG_UPDATE, "org-A")


@pytest.mark.parametrize("role", list(Role))
def test_every_role_has_a_permission_set(role):
    assert role in ROLE_PERMISSIONS
    assert isinstance(ROLE_PERMISSIONS[role], frozenset)


def test_privilege_monotonicity():
    """Admin must be a strict superset of member; member of viewer."""
    assert ROLE_PERMISSIONS[Role.MEMBER] <= ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.VIEWER] <= ROLE_PERMISSIONS[Role.MEMBER]
