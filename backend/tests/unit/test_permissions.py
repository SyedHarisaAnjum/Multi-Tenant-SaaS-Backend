"""Role-permission rules (app/core/permissions.py), exhaustively. No database."""

import uuid

import pytest

from app.core.exceptions import PermissionDeniedError
from app.core.permissions import CONTRIBUTOR_ROLES, MANAGER_ROLES, ensure_can_manage
from app.db.models import Membership, MembershipRole
from app.dependencies.organizations import require_role

OWNER, ADMIN, MEMBER, VIEWER = (
    MembershipRole.OWNER,
    MembershipRole.ADMIN,
    MembershipRole.MEMBER,
    MembershipRole.VIEWER,
)


def _m(role: MembershipRole) -> Membership:
    return Membership(organization_id=uuid.uuid4(), user_id=uuid.uuid4(), role=role)


# (actor, target/granted role) → allowed?
MANAGE_MATRIX = {
    (OWNER, OWNER): False,  # nobody manages or grants their own level
    (OWNER, ADMIN): True,
    (OWNER, MEMBER): True,
    (OWNER, VIEWER): True,
    (ADMIN, OWNER): False,
    (ADMIN, ADMIN): False,  # admins can't create or manage other admins
    (ADMIN, MEMBER): True,
    (ADMIN, VIEWER): True,
    (MEMBER, OWNER): False,
    (MEMBER, ADMIN): False,
    (MEMBER, MEMBER): False,
    (MEMBER, VIEWER): False,  # outranking isn't enough: members aren't managers
    (VIEWER, OWNER): False,
    (VIEWER, ADMIN): False,
    (VIEWER, MEMBER): False,
    (VIEWER, VIEWER): False,
}


@pytest.mark.parametrize(("actor", "target"), list(MANAGE_MATRIX))
def test_ensure_can_manage_matrix(actor: MembershipRole, target: MembershipRole) -> None:
    if MANAGE_MATRIX[(actor, target)]:
        ensure_can_manage(_m(actor), target)
    else:
        with pytest.raises(PermissionDeniedError):
            ensure_can_manage(_m(actor), target)


def test_matrix_covers_every_pair() -> None:
    assert len(MANAGE_MATRIX) == len(MembershipRole) ** 2


def test_role_ranking_is_strict_total_order() -> None:
    ordered = [VIEWER, MEMBER, ADMIN, OWNER]
    for lower, higher in zip(ordered, ordered[1:], strict=False):
        assert higher.outranks(lower) and not lower.outranks(higher)
    assert not ADMIN.outranks(ADMIN)


def test_role_groups() -> None:
    assert frozenset({OWNER, ADMIN}) == MANAGER_ROLES
    assert frozenset({OWNER, ADMIN, MEMBER}) == CONTRIBUTOR_ROLES


@pytest.mark.parametrize("role", list(MembershipRole))
def test_require_role_dependency(role: MembershipRole) -> None:
    check = require_role(OWNER, ADMIN)
    membership = _m(role)
    if role in (OWNER, ADMIN):
        assert check(membership) is membership
    else:
        with pytest.raises(PermissionDeniedError):
            check(membership)
