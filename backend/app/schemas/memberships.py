import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel

from app.db.models import MembershipRole


def _not_owner(role: MembershipRole) -> MembershipRole:
    if role is MembershipRole.OWNER:
        raise ValueError("Ownership can't be assigned; use the transfer-ownership endpoint.")
    return role


# Roles that can be granted by role change or invitation.
AssignableRole = Annotated[MembershipRole, AfterValidator(_not_owner)]


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: MembershipRole
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    role: AssignableRole


class OwnershipTransfer(BaseModel):
    user_id: uuid.UUID
