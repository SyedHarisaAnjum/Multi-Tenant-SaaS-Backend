import uuid

from fastapi import APIRouter, status

from app.api.v1.organizations import with_role
from app.dependencies.auth import CurrentUser, DbSession
from app.dependencies.organizations import OrgAdmin
from app.schemas.invitations import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
)
from app.schemas.organizations import OrganizationWithRole
from app.services.invitation_service import InvitationService

router = APIRouter(tags=["invitations"])


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    data: InvitationCreate, membership: OrgAdmin, db: DbSession
) -> InvitationCreated:
    invitation, token = InvitationService(db).create(membership, data)
    return InvitationCreated(**InvitationRead.model_validate(invitation).model_dump(), token=token)


@router.get("/organizations/{organization_id}/invitations", response_model=list[InvitationRead])
def list_pending_invitations(membership: OrgAdmin, db: DbSession) -> list[InvitationRead]:
    return [
        InvitationRead.model_validate(invitation)
        for invitation in InvitationService(db).list_pending(membership.organization_id)
    ]


@router.delete(
    "/organizations/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(invitation_id: uuid.UUID, membership: OrgAdmin, db: DbSession) -> None:
    InvitationService(db).revoke(membership, invitation_id)


@router.post("/invitations/accept", response_model=OrganizationWithRole)
def accept_invitation(
    data: InvitationAccept, user: CurrentUser, db: DbSession
) -> OrganizationWithRole:
    organization, membership = InvitationService(db).accept(user, data.token)
    return with_role(organization, membership.role)
