import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Membership, User


class MembershipRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        return self.db.scalar(
            select(Membership).where(
                Membership.organization_id == organization_id, Membership.user_id == user_id
            )
        )

    def get_for_update(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        # populate_existing: the row may already be in the session from an
        # earlier unlocked read; reload it so checks see the locked values.
        return self.db.scalar(
            select(Membership)
            .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def get_with_user(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Membership, User] | None:
        row = self.db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
        ).one_or_none()
        return (row[0], row[1]) if row else None

    def list_with_users(self, organization_id: uuid.UUID) -> list[tuple[Membership, User]]:
        rows = self.db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at, Membership.id)
        )
        return [(membership, user) for membership, user in rows]

    def add(self, membership: Membership) -> Membership:
        self.db.add(membership)
        self.db.flush()
        return membership

    def delete(self, membership: Membership) -> None:
        self.db.delete(membership)
        self.db.flush()
