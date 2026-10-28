import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import MembershipRole
from app.schemas.auth import NormalizedEmail
from app.schemas.common import RequestModel
from app.schemas.memberships import AssignableRole


class InvitationCreate(RequestModel):
    email: NormalizedEmail
    role: AssignableRole = MembershipRole.MEMBER


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: MembershipRole
    invited_by_id: uuid.UUID | None
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationRead):
    # Returned exactly once. In production this goes into the invitation email link
    # instead of the API response; the server keeps only its hash.
    token: str


class InvitationAccept(RequestModel):
    token: Annotated[str, Field(min_length=1, max_length=200)]
