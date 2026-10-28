from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import cache
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.db.models import Membership, Project, Workspace
from app.dependencies.resources import load_tenant_resource
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.projects import ProjectCreate, ProjectUpdate

_NAME_TAKEN = "A project with this name already exists in the workspace."


def ensure_version(current: int, expected: int) -> None:
    """Optimistic concurrency: reject updates based on a stale read."""
    if current != expected:
        raise ConflictError(
            "This resource was modified by someone else. Reload it and try again.",
            code="VERSION_CONFLICT",
            details=[{"field": "version", "current_version": current}],
        )


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.activity = ActivityLogRepository(db)

    def create(self, actor: Membership, data: ProjectCreate) -> Project:
        # Tenant scope comes from the caller's membership; the body can only name a
        # workspace, and that workspace must belong to the same organization.
        self._ensure_workspace_in_org(actor, data.workspace_id)
        if self.projects.name_taken(data.workspace_id, data.name):
            raise ConflictError(_NAME_TAKEN, code="PROJECT_NAME_TAKEN")
        try:
            project = self.projects.add(
                Project(
                    organization_id=actor.organization_id,
                    workspace_id=data.workspace_id,
                    name=data.name,
                    description=data.description,
                    status=data.status,
                )
            )
            self._log(actor, "project.created", project, {"name": project.name})
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(_NAME_TAKEN, code="PROJECT_NAME_TAKEN") from None
        self._invalidate(actor)
        return project

    def update(self, actor: Membership, project: Project, data: ProjectUpdate) -> Project:
        ensure_version(project.version, data.version)
        changes = {
            k: v for k, v in data.changes().items() if k != "version" and getattr(project, k) != v
        }
        if not changes:
            return project
        if "workspace_id" in changes:
            self._ensure_workspace_in_org(actor, changes["workspace_id"])
        if {"name", "workspace_id"} & changes.keys() and self.projects.name_taken(
            changes.get("workspace_id", project.workspace_id),
            changes.get("name", project.name),
            exclude_id=project.id,
        ):
            raise ConflictError(_NAME_TAKEN, code="PROJECT_NAME_TAKEN")

        for field, value in changes.items():
            setattr(project, field, value)
        self._log(actor, "project.updated", project, {"fields": sorted(changes)})
        try:
            self.db.commit()  # UPDATE ... WHERE version = :read_version (StaleDataError → 409)
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(_NAME_TAKEN, code="PROJECT_NAME_TAKEN") from None
        self.db.refresh(project)
        self._invalidate(actor)
        return project

    def delete(self, actor: Membership, project: Project) -> None:
        """Deletes the project and (via ON DELETE CASCADE) its tasks, in one transaction."""
        self._log(actor, "project.deleted", project, {"name": project.name})
        self.projects.delete(project)
        self.db.commit()
        self._invalidate(actor)

    def _ensure_workspace_in_org(self, actor: Membership, workspace_id: Any) -> None:
        try:
            load_tenant_resource(self.db, Workspace, workspace_id, actor.organization_id)
        except NotFoundError:
            # Same answer whether the workspace is missing or in another organization.
            raise UnprocessableError(
                "The workspace does not exist in this organization.",
                code="WORKSPACE_NOT_FOUND",
                details=[{"field": "body.workspace_id"}],
            ) from None

    def _log(
        self, actor: Membership, action: str, project: Project, details: dict[str, Any]
    ) -> None:
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action=action,
            entity_type="project",
            entity_id=project.id,
            details=details,
        )

    @staticmethod
    def _invalidate(actor: Membership) -> None:
        cache.get_cache().invalidate(actor.organization_id, cache.PROJECTS, cache.SUMMARY)
