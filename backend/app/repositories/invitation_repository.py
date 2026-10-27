import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Invitation


class InvitationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_hash_for_update(self, token_hash: str) -> Invitation | None:
        # Row lock: two concurrent accepts of the same token can't both succeed.
        return self.db.scalar(
            select(Invitation).where(Invitation.token_hash == token_hash).with_for_update()
        )

    def get_in_org_for_update(
        self, organization_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> Invitation | None:
        return self.db.scalar(
            select(Invitation)
            .where(Invitation.id == invitation_id, Invitation.organization_id == organization_id)
            .with_for_update()
        )

    def get_open_for_email_for_update(
        self, organization_id: uuid.UUID, email: str
    ) -> Invitation | None:
        """The not-yet-accepted, not-revoked invitation for this email (possibly expired)."""
        return self.db.scalar(
            select(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .with_for_update()
        )

    def list_pending(self, organization_id: uuid.UUID, now: datetime) -> list[Invitation]:
        return list(
            self.db.scalars(
                select(Invitation)
                .where(
                    Invitation.organization_id == organization_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                    Invitation.expires_at > now,
                )
                .order_by(Invitation.created_at, Invitation.id)
            )
        )

    def add(self, invitation: Invitation) -> Invitation:
        self.db.add(invitation)
        self.db.flush()
        return invitation
