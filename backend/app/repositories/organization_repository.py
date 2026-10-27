import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Membership, MembershipRole, Organization


class OrganizationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, organization_id: uuid.UUID) -> Organization | None:
        return self.db.get(Organization, organization_id)

    def get_by_slug(self, slug: str) -> Organization | None:
        return self.db.scalar(select(Organization).where(Organization.slug == slug))

    def add(self, organization: Organization) -> Organization:
        self.db.add(organization)
        self.db.flush()
        return organization

    def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Organization, MembershipRole]]:
        rows = self.db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.name, Organization.id)
        )
        return [(org, role) for org, role in rows]
