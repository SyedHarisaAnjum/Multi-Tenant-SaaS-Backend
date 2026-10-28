from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import cache
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Membership, Workspace
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspaces import WorkspaceCreate, WorkspaceUpdate

_SLUG_TAKEN = "A workspace with this slug already exists in the organization."


class WorkspaceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.workspaces = WorkspaceRepository(db)
        self.activity = ActivityLogRepository(db)

    def create(self, actor: Membership, data: WorkspaceCreate) -> Workspace:
        if self.workspaces.get_by_slug(actor.organization_id, data.slug):
            raise ConflictError(_SLUG_TAKEN, code="WORKSPACE_SLUG_TAKEN")
        try:
            workspace = self.workspaces.add(
                Workspace(organization_id=actor.organization_id, name=data.name, slug=data.slug)
            )
            self._log(actor, "workspace.created", workspace)
            self.db.commit()
        except IntegrityError:
            # Lost a race with a concurrent create of the same slug.
            self.db.rollback()
            raise ConflictError(_SLUG_TAKEN, code="WORKSPACE_SLUG_TAKEN") from None
        self._invalidate(actor)
        return workspace

    def update(self, actor: Membership, workspace: Workspace, data: WorkspaceUpdate) -> Workspace:
        changes = {k: v for k, v in data.changes().items() if getattr(workspace, k) != v}
        if not changes:
            return workspace
        new_slug = changes.get("slug")
        if new_slug and self.workspaces.get_by_slug(actor.organization_id, new_slug):
            raise ConflictError(_SLUG_TAKEN, code="WORKSPACE_SLUG_TAKEN")
        for field, value in changes.items():
            setattr(workspace, field, value)
        self._log(actor, "workspace.updated", workspace, {"fields": sorted(changes)})
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(_SLUG_TAKEN, code="WORKSPACE_SLUG_TAKEN") from None
        self.db.refresh(workspace)
        self._invalidate(actor)
        return workspace

    def delete(self, actor: Membership, workspace: Workspace) -> None:
        """MVP policy: refuse while the workspace still has projects (no cascading delete)."""
        # Lock the row so a project can't be created into it between check and delete.
        # (The RESTRICT foreign key is the backstop if anything slips through.)
        locked = self.workspaces.get_for_update(actor.organization_id, workspace.id)
        if locked is None:
            raise NotFoundError("Workspace not found.", code="WORKSPACE_NOT_FOUND")
        if self.workspaces.has_projects(locked.id):
            raise ConflictError(
                "Move or delete this workspace's projects before deleting it.",
                code="WORKSPACE_NOT_EMPTY",
            )
        self._log(actor, "workspace.deleted", locked, {"slug": locked.slug})
        self.workspaces.delete(locked)
        self.db.commit()
        self._invalidate(actor)

    def _log(
        self,
        actor: Membership,
        action: str,
        workspace: Workspace,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action=action,
            entity_type="workspace",
            entity_id=workspace.id,
            details=details,
        )

    @staticmethod
    def _invalidate(actor: Membership) -> None:
        cache.get_cache().invalidate(actor.organization_id, cache.WORKSPACES, cache.SUMMARY)
