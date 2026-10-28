from typing import Any

from fastapi import APIRouter, Response, status

from app.api.v1.pagination import mark_cache, to_page
from app.core import cache
from app.dependencies.auth import DbSession
from app.dependencies.organizations import CurrentMembership, OrgAdmin
from app.dependencies.pagination import Pagination, SearchQuery, SortQuery
from app.dependencies.resources import AccessibleWorkspace
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.common import Page
from app.schemas.workspaces import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/organizations/{organization_id}/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(data: WorkspaceCreate, membership: OrgAdmin, db: DbSession) -> Any:
    return WorkspaceService(db).create(membership, data)


@router.get("", response_model=Page[WorkspaceRead])
def list_workspaces(
    membership: CurrentMembership,
    db: DbSession,
    params: Pagination,
    response: Response,
    q: SearchQuery = None,
    sort: SortQuery = None,
) -> Any:
    # Membership was verified above; the cached page is the same for every member.
    def load() -> dict[str, Any]:
        items, total = WorkspaceRepository(db).list(
            membership.organization_id, params, search=q, sort=sort
        )
        return to_page(WorkspaceRead, items, total, params).model_dump(mode="json")

    data, hit = cache.get_cache().get_or_load(
        membership.organization_id,
        cache.WORKSPACES,
        {"page": params.page, "page_size": params.page_size, "q": q, "sort": sort},
        load,
    )
    mark_cache(response, hit)
    return data


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(workspace: AccessibleWorkspace) -> Any:
    return workspace


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    data: WorkspaceUpdate, workspace: AccessibleWorkspace, membership: OrgAdmin, db: DbSession
) -> Any:
    return WorkspaceService(db).update(membership, workspace, data)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace: AccessibleWorkspace, membership: OrgAdmin, db: DbSession) -> None:
    """Refused with 409 WORKSPACE_NOT_EMPTY while the workspace still has projects."""
    WorkspaceService(db).delete(membership, workspace)
