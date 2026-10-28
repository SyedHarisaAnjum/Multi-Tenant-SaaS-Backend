"""Tenant authorization dependencies.

Every organization-scoped route takes `organization_id` from its path and depends on
`get_current_membership`, which looks up the caller's membership *on every request*.
Access is never inferred from the token alone, so removing a member or changing
their role takes effect immediately, even for access tokens that are still valid.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.models import Membership, MembershipRole
from app.dependencies.auth import CurrentUser, DbSession
from app.repositories.membership_repository import MembershipRepository


def get_current_membership(
    organization_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Membership:
    membership = MembershipRepository(db).get(organization_id, user.id)
    if membership is None:
        # 404, not 403: outsiders can't tell whether the organization exists.
        raise NotFoundError("Organization not found.", code="ORGANIZATION_NOT_FOUND")
    return membership


CurrentMembership = Annotated[Membership, Depends(get_current_membership)]


def require_role(*allowed_roles: MembershipRole) -> Callable[[Membership], Membership]:
    """Dependency factory: the caller's membership, if their role is one of `allowed_roles`."""
    allowed = frozenset(allowed_roles)

    def dependency(membership: CurrentMembership) -> Membership:
        if membership.role not in allowed:
            raise PermissionDeniedError("You don't have permission to perform this action.")
        return membership

    return dependency


OrgOwner = Annotated[Membership, Depends(require_role(MembershipRole.OWNER))]
OrgAdmin = Annotated[Membership, Depends(require_role(MembershipRole.OWNER, MembershipRole.ADMIN))]
# Can create and modify work items; viewers are read-only.
OrgContributor = Annotated[
    Membership,
    Depends(require_role(MembershipRole.OWNER, MembershipRole.ADMIN, MembershipRole.MEMBER)),
]
