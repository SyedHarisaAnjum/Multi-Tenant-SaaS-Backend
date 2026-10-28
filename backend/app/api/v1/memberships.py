import uuid

from fastapi import APIRouter, status

from app.core.exceptions import NotFoundError
from app.db.models import Membership, User
from app.dependencies.auth import DbSession
from app.dependencies.organizations import CurrentMembership, OrgAdmin, OrgOwner
from app.repositories.membership_repository import MembershipRepository
from app.schemas.memberships import MemberRead, MemberRoleUpdate, OwnershipTransfer
from app.services.membership_service import MembershipService

router = APIRouter(prefix="/organizations/{organization_id}", tags=["memberships"])


def _member_read(member: Membership, user: User) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        joined_at=member.created_at,
    )


@router.get("/members", response_model=list[MemberRead])
def list_members(membership: CurrentMembership, db: DbSession) -> list[MemberRead]:
    return [
        _member_read(member, user)
        for member, user in MembershipService(db).list_members(membership.organization_id)
    ]


@router.patch("/members/{user_id}", response_model=MemberRead)
def update_member_role(
    user_id: uuid.UUID, data: MemberRoleUpdate, membership: OrgAdmin, db: DbSession
) -> MemberRead:
    MembershipService(db).change_role(membership, user_id, data.role)
    row = MembershipRepository(db).get_with_user(membership.organization_id, user_id)
    if row is None:
        raise NotFoundError("Member not found.", code="MEMBER_NOT_FOUND")
    return _member_read(*row)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, membership: CurrentMembership, db: DbSession) -> None:
    """Remove a member (owner/admin), or leave the organization (pass your own user id)."""
    MembershipService(db).remove(membership, user_id)


@router.post("/transfer-ownership", status_code=status.HTTP_204_NO_CONTENT)
def transfer_ownership(data: OwnershipTransfer, membership: OrgOwner, db: DbSession) -> None:
    """Make another member the owner. The current owner becomes an admin."""
    MembershipService(db).transfer_ownership(membership, data.user_id)
