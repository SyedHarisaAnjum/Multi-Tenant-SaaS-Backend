"""Load tenant-owned resources only through the caller's verified membership.

Never fetch a resource by id alone. Two shapes:

* Org in the path (`/organizations/{organization_id}/workspaces/{workspace_id}`):
  membership is resolved first, then the resource is loaded *within* that organization.

* Resource id only (`/projects/{project_id}`, `/tasks/{task_id}`): the resource is
  loaded in the same query as the caller's membership in its organization (an inner
  join on the caller's user id). Non-members get no row, i.e. 404, the same as for an
  id that doesn't exist. The tenant comes from the stored row, never from the client.

Either way, a resource in another tenant is indistinguishable from a missing one.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated, Generic, TypeVar

from fastapi import Depends
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.models import Membership, MembershipRole, Project, Task, Workspace
from app.dependencies.auth import CurrentUser, DbSession
from app.dependencies.organizations import CurrentMembership

TenantModel = TypeVar("TenantModel", Workspace, Project, Task)


def _not_found(model: type[TenantModel]) -> NotFoundError:
    return NotFoundError(f"{model.__name__} not found.", code=f"{model.__name__.upper()}_NOT_FOUND")


def load_tenant_resource(
    db: Session, model: type[TenantModel], resource_id: uuid.UUID, organization_id: uuid.UUID
) -> TenantModel:
    resource = db.scalar(
        select(model).where(model.id == resource_id, model.organization_id == organization_id)
    )
    if resource is None:
        raise _not_found(model)
    return resource


@dataclass(frozen=True)
class Scoped(Generic[TenantModel]):
    """A resource plus the caller's membership in the organization that owns it."""

    resource: TenantModel
    membership: Membership

    def require(self, *roles: MembershipRole) -> Membership:
        if self.membership.role not in roles:
            raise PermissionDeniedError("You don't have permission to perform this action.")
        return self.membership


def load_scoped(
    db: Session, model: type[TenantModel], resource_id: uuid.UUID, user_id: uuid.UUID
) -> Scoped[TenantModel]:
    row = db.execute(
        select(model, Membership)
        .join(
            Membership,
            and_(
                Membership.organization_id == model.organization_id,
                Membership.user_id == user_id,
            ),
        )
        .where(model.id == resource_id)
    ).one_or_none()
    if row is None:
        raise _not_found(model)
    return Scoped(resource=row[0], membership=row[1])


# --- org-in-path forms ---------------------------------------------------------------


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


# --- resource-id-only forms ----------------------------------------------------------


def get_project_scope(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Scoped[Project]:
    return load_scoped(db, Project, project_id, user.id)


def get_task_scope(task_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Scoped[Task]:
    return load_scoped(db, Task, task_id, user.id)


ProjectScope = Annotated[Scoped[Project], Depends(get_project_scope)]
TaskScope = Annotated[Scoped[Task], Depends(get_task_scope)]
