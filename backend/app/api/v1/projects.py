import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.v1.pagination import mark_cache, to_page
from app.core import cache
from app.core.permissions import CONTRIBUTOR_ROLES, MANAGER_ROLES
from app.db.models import ProjectStatus
from app.dependencies.auth import DbSession
from app.dependencies.organizations import CurrentMembership, OrgContributor
from app.dependencies.pagination import Pagination, SearchQuery, SortQuery
from app.dependencies.resources import ProjectScope
from app.repositories.project_repository import ProjectFilters, ProjectRepository
from app.schemas.common import Page
from app.schemas.projects import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(tags=["projects"])


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project(data: ProjectCreate, membership: OrgContributor, db: DbSession) -> Any:
    return ProjectService(db).create(membership, data)


@router.get("/organizations/{organization_id}/projects", response_model=Page[ProjectRead])
def list_projects(
    membership: CurrentMembership,
    db: DbSession,
    params: Pagination,
    response: Response,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
    status_: Annotated[ProjectStatus | None, Query(alias="status")] = None,
    q: SearchQuery = None,
    sort: SortQuery = None,
) -> Any:
    filters = ProjectFilters(workspace_id=workspace_id, status=status_, search=q)

    def load() -> dict[str, Any]:
        items, total = ProjectRepository(db).list(membership.organization_id, params, filters, sort)
        return to_page(ProjectRead, items, total, params).model_dump(mode="json")

    data, hit = cache.get_cache().get_or_load(
        membership.organization_id,
        cache.PROJECTS,
        {
            "page": params.page,
            "page_size": params.page_size,
            "workspace_id": workspace_id,
            "status": status_,
            "q": q,
            "sort": sort,
        },
        load,
    )
    mark_cache(response, hit)
    return data


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(scope: ProjectScope) -> Any:
    return scope.resource


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(data: ProjectUpdate, scope: ProjectScope, db: DbSession) -> Any:
    membership = scope.require(*CONTRIBUTOR_ROLES)
    return ProjectService(db).update(membership, scope.resource, data)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(scope: ProjectScope, db: DbSession) -> None:
    """Owners and admins only. Deletes the project's tasks with it."""
    membership = scope.require(*MANAGER_ROLES)
    ProjectService(db).delete(membership, scope.resource)
