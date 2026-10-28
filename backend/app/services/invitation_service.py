import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import cache, security
from app.core.config import get_settings
from app.core.exceptions import ConflictError, GoneError, NotFoundError, PermissionDeniedError
from app.core.permissions import ensure_can_manage
from app.db.models import Invitation, Membership, Organization, User
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.invitations import InvitationCreate


def ensure_invitation_usable(invitation: Invitation, email: str, now: datetime) -> None:
    """Raise unless `email` may accept `invitation` at `now`. Pure: no database access."""
    # Check identity before revealing anything about the invitation's state.
    if invitation.email != email:
        raise PermissionDeniedError(
            "This invitation was sent to a different email address.",
            code="INVITATION_EMAIL_MISMATCH",
        )
    if invitation.revoked_at is not None:
        raise GoneError("This invitation has been revoked.", code="INVITATION_REVOKED")
    if invitation.accepted_at is not None:
        raise GoneError("This invitation has already been used.", code="INVITATION_ALREADY_USED")
    if invitation.expires_at <= now:
        raise GoneError("This invitation has expired.", code="INVITATION_EXPIRED")


class InvitationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.invitations = InvitationRepository(db)
        self.memberships = MembershipRepository(db)
        self.activity = ActivityLogRepository(db)

    def create(self, actor: Membership, data: InvitationCreate) -> tuple[Invitation, str]:
        """Create an invitation; returns it with the raw token (never stored)."""
        ensure_can_manage(actor, data.role)
        organization_id = actor.organization_id

        invitee = UserRepository(self.db).get_by_email(data.email)
        if invitee and self.memberships.get(organization_id, invitee.id):
            raise ConflictError(
                "This user is already a member of the organization.", code="ALREADY_MEMBER"
            )

        now = datetime.now(timezone.utc)
        # Re-inviting replaces the previous link, so only the newest one works.
        previous = self.invitations.get_open_for_email_for_update(organization_id, data.email)
        if previous is not None:
            ensure_can_manage(actor, previous.role)
            previous.revoked_at = now
            self.db.flush()

        raw_token = security.generate_opaque_token()
        invitation = self.invitations.add(
            Invitation(
                organization_id=organization_id,
                email=data.email,
                role=data.role,
                token_hash=security.hash_opaque_token(raw_token),
                invited_by_id=actor.user_id,
                expires_at=now + timedelta(hours=get_settings().invitation_expire_hours),
            )
        )
        self.activity.record(
            organization_id=organization_id,
            actor_id=actor.user_id,
            action="invitation.created",
            entity_type="invitation",
            entity_id=invitation.id,
            details={"email": data.email, "role": data.role.value},
        )
        self.db.commit()
        return invitation, raw_token

    def list_pending(self, organization_id: uuid.UUID) -> list[Invitation]:
        return self.invitations.list_pending(organization_id, datetime.now(timezone.utc))

    def revoke(self, actor: Membership, invitation_id: uuid.UUID) -> None:
        invitation = self.invitations.get_in_org_for_update(actor.organization_id, invitation_id)
        if invitation is None:
            raise NotFoundError("Invitation not found.", code="INVITATION_NOT_FOUND")
        if invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise ConflictError(
                "This invitation is no longer pending.", code="INVITATION_NOT_PENDING"
            )
        ensure_can_manage(actor, invitation.role)

        invitation.revoked_at = datetime.now(timezone.utc)
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action="invitation.revoked",
            entity_type="invitation",
            entity_id=invitation.id,
        )
        self.db.commit()

    def accept(self, user: User, raw_token: str) -> tuple[Organization, Membership]:
        invitation = self.invitations.get_by_hash_for_update(security.hash_opaque_token(raw_token))
        if invitation is None:
            raise NotFoundError("Invitation not found.", code="INVITATION_NOT_FOUND")
        now = datetime.now(timezone.utc)
        ensure_invitation_usable(invitation, user.email, now)
        if self.memberships.get(invitation.organization_id, user.id):
            raise ConflictError(
                "You are already a member of this organization.", code="ALREADY_MEMBER"
            )
        organization = OrganizationRepository(self.db).get(invitation.organization_id)
        if organization is None:
            raise NotFoundError("Invitation not found.", code="INVITATION_NOT_FOUND")

        try:
            membership = self.memberships.add(
                Membership(
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    role=invitation.role,
                )
            )
        except IntegrityError:
            # Joined concurrently through another invitation.
            self.db.rollback()
            raise ConflictError(
                "You are already a member of this organization.", code="ALREADY_MEMBER"
            ) from None
        invitation.accepted_at = now
        invitation.accepted_by_id = user.id
        self.activity.record(
            organization_id=invitation.organization_id,
            actor_id=user.id,
            action="invitation.accepted",
            entity_type="invitation",
            entity_id=invitation.id,
            details={"role": invitation.role.value},
        )
        self.db.commit()
        cache.get_cache().invalidate(organization.id, cache.SUMMARY)
        return organization, membership
