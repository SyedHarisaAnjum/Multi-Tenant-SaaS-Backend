from fastapi import APIRouter, status

from app.core.exceptions import NotFoundError
from app.db.models import MembershipRole, Organization
from app.dependencies.auth import CurrentUser, DbSession
from app.dependencies.organizations import CurrentMembership, OrgAdmin
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organizations import OrganizationCreate, OrganizationUpdate, OrganizationWithRole
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


def with_role(organization: Organization, role: MembershipRole) -> OrganizationWithRole:
    return OrganizationWithRole(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        role=role,
    )


@router.post("", response_model=OrganizationWithRole, status_code=status.HTTP_201_CREATED)
def create_organization(
    data: OrganizationCreate, user: CurrentUser, db: DbSession
) -> OrganizationWithRole:
    organization, membership = OrganizationService(db).create(user, data)
    return with_role(organization, membership.role)


@router.get("", response_model=list[OrganizationWithRole])
def list_my_organizations(user: CurrentUser, db: DbSession) -> list[OrganizationWithRole]:
    return [with_role(org, role) for org, role in OrganizationRepository(db).list_for_user(user.id)]


@router.get("/{organization_id}", response_model=OrganizationWithRole)
def get_organization(membership: CurrentMembership, db: DbSession) -> OrganizationWithRole:
    organization = OrganizationRepository(db).get(membership.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")
    return with_role(organization, membership.role)


@router.patch("/{organization_id}", response_model=OrganizationWithRole)
def update_organization(
    data: OrganizationUpdate, membership: OrgAdmin, db: DbSession
) -> OrganizationWithRole:
    organization = OrganizationService(db).update(membership, data)
    return with_role(organization, membership.role)
