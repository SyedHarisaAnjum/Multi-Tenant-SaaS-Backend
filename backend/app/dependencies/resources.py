"""Load tenant-owned resources only through the caller's verified membership.

Never fetch a resource by id alone: every query below also filters by the
organization the caller is a *current* member of. A resource in another tenant is
indistinguishable from one that doesn't exist (404).

Use the dependency forms in routes nested under /organizations/{organization_id}:

    def update_task(task: AccessibleTask, _: OrgContributor) -> ...
"""

import uuid
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import Project, Task, Workspace
from app.dependencies.auth import DbSession
from app.dependencies.organizations import CurrentMembership

TenantModel = TypeVar("TenantModel", Workspace, Project, Task)


def load_tenant_resource(
    db: Session, model: type[TenantModel], resource_id: uuid.UUID, organization_id: uuid.UUID
) -> TenantModel:
    resource = db.scalar(
        select(model).where(model.id == resource_id, model.organization_id == organization_id)
    )
    if resource is None:
        raise NotFoundError(f"{model.__name__} not found.")
    return resource


def get_accessible_workspace(
    workspace_id: uuid.UUID, membership: CurrentMembership, db: DbSession
) -> Workspace:
    return load_tenant_resource(db, Workspace, workspace_id, membership.organization_id)


def get_accessible_project(
    project_id: uuid.UUID, membership: CurrentMembership, db: DbSession
) -> Project:
    return load_tenant_resource(db, Project, project_id, membership.organization_id)


def get_accessible_task(task_id: uuid.UUID, membership: CurrentMembership, db: DbSession) -> Task:
    return load_tenant_resource(db, Task, task_id, membership.organization_id)


AccessibleWorkspace = Annotated[Workspace, Depends(get_accessible_workspace)]
AccessibleProject = Annotated[Project, Depends(get_accessible_project)]
AccessibleTask = Annotated[Task, Depends(get_accessible_task)]
