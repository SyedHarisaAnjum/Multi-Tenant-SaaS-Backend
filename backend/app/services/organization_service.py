from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Membership, MembershipRole, Organization, User
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organizations import OrganizationCreate, OrganizationUpdate

_SLUG_TAKEN = "An organization with this slug already exists."


class OrganizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.organizations = OrganizationRepository(db)
        self.memberships = MembershipRepository(db)
        self.activity = ActivityLogRepository(db)

    def create(self, creator: User, data: OrganizationCreate) -> tuple[Organization, Membership]:
        """Create the organization and the creator's owner membership atomically."""
        if self.organizations.get_by_slug(data.slug):
            raise ConflictError(_SLUG_TAKEN)
        try:
            organization = self.organizations.add(Organization(name=data.name, slug=data.slug))
            membership = self.memberships.add(
                Membership(
                    organization_id=organization.id,
                    user_id=creator.id,
                    role=MembershipRole.OWNER,
                )
            )
            self.activity.record(
                organization_id=organization.id,
                actor_id=creator.id,
                action="organization.created",
                entity_type="organization",
                entity_id=organization.id,
            )
            self.db.commit()
        except IntegrityError:
            # Lost a race for the slug.
            self.db.rollback()
            raise ConflictError(_SLUG_TAKEN) from None
        except Exception:
            # Neither the organization nor the membership may survive alone.
            self.db.rollback()
            raise
        return organization, membership

    def update(self, actor: Membership, data: OrganizationUpdate) -> Organization:
        organization = self.organizations.get(actor.organization_id)
        if organization is None:
            raise NotFoundError("Organization not found.")

        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        new_slug = changes.get("slug")
        if new_slug and new_slug != organization.slug and self.organizations.get_by_slug(new_slug):
            raise ConflictError(_SLUG_TAKEN)
        changes = {k: v for k, v in changes.items() if getattr(organization, k) != v}
        if not changes:
            return organization

        for field, value in changes.items():
            setattr(organization, field, value)
        self.activity.record(
            organization_id=organization.id,
            actor_id=actor.user_id,
            action="organization.updated",
            entity_type="organization",
            entity_id=organization.id,
            details={"fields": sorted(changes)},
        )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(_SLUG_TAKEN) from None
        self.db.refresh(organization)
        return organization
