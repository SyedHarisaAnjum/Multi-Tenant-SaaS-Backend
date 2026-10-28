import uuid
from dataclasses import replace
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.pagination import to_page
from app.core.permissions import CONTRIBUTOR_ROLES
from app.db.models import TaskPriority, TaskStatus
from app.dependencies.auth import DbSession
from app.dependencies.organizations import CurrentMembership
from app.dependencies.pagination import Pagination, SearchQuery, SortQuery
from app.dependencies.resources import ProjectScope, TaskScope
from app.repositories.task_repository import TaskFilters, TaskRepository
from app.schemas.common import Page
from app.schemas.tasks import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import TaskService

router = APIRouter(tags=["tasks"])


def task_filters(
    status_: Annotated[TaskStatus | None, Query(alias="status")] = None,
    priority: Annotated[TaskPriority | None, Query()] = None,
    assignee_id: Annotated[uuid.UUID | None, Query()] = None,
    due_before: Annotated[date | None, Query(description="Due on or before.")] = None,
    due_after: Annotated[date | None, Query(description="Due on or after.")] = None,
    q: SearchQuery = None,
) -> TaskFilters:
    return TaskFilters(
        status=status_,
        priority=priority,
        assignee_id=assignee_id,
        due_before=due_before,
        due_after=due_after,
        search=q,
    )


Filters = Annotated[TaskFilters, Depends(task_filters)]


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED
)
def create_task(data: TaskCreate, scope: ProjectScope, db: DbSession) -> Any:
    membership = scope.require(*CONTRIBUTOR_ROLES)
    return TaskService(db).create(membership, scope.resource, data)


@router.get("/projects/{project_id}/tasks", response_model=Page[TaskRead])
def list_project_tasks(
    scope: ProjectScope, db: DbSession, params: Pagination, filters: Filters, sort: SortQuery = None
) -> Any:
    project = scope.resource
    items, total = TaskRepository(db).list(
        project.organization_id, params, replace(filters, project_id=project.id), sort
    )
    return to_page(TaskRead, items, total, params)


@router.get("/organizations/{organization_id}/tasks", response_model=Page[TaskRead])
def list_organization_tasks(
    membership: CurrentMembership,
    db: DbSession,
    params: Pagination,
    filters: Filters,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_to_me: Annotated[bool, Query(description="Shortcut for assignee_id=<you>.")] = False,
    sort: SortQuery = None,
) -> Any:
    """Tasks across the organization; filter by `assignee_id` to list someone's work."""
    if assigned_to_me:
        filters = replace(filters, assignee_id=membership.user_id)
    items, total = TaskRepository(db).list(
        membership.organization_id, params, replace(filters, project_id=project_id), sort
    )
    return to_page(TaskRead, items, total, params)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(scope: TaskScope) -> Any:
    return scope.resource


@router.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(data: TaskUpdate, scope: TaskScope, db: DbSession) -> Any:
    """Edit fields, assign/unassign (`assignee_id`), move status, or change `due_date`.
    Requires the current `version`."""
    membership = scope.require(*CONTRIBUTOR_ROLES)
    return TaskService(db).update(membership, scope.resource, data)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(scope: TaskScope, db: DbSession) -> None:
    """The task's creator, or an owner/admin."""
    membership = scope.require(*CONTRIBUTOR_ROLES)
    TaskService(db).delete(membership, scope.resource)
