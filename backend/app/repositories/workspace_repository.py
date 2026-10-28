import uuid
from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Project, Workspace
from app.dependencies.pagination import PageParams
from app.repositories.query_utils import apply_sort, contains_ci, paginate

WORKSPACE_SORTS = {
    "name": Workspace.name,
    "slug": Workspace.slug,
    "created_at": Workspace.created_at,
    "updated_at": Workspace.updated_at,
}


class WorkspaceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_slug(self, organization_id: uuid.UUID, slug: str) -> Workspace | None:
        return self.db.scalar(
            select(Workspace).where(
                Workspace.organization_id == organization_id, Workspace.slug == slug
            )
        )

    def get_for_update(
        self, organization_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Workspace | None:
        return self.db.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id, Workspace.organization_id == organization_id)
            .with_for_update()
        )

    def has_projects(self, workspace_id: uuid.UUID) -> bool:
        return bool(self.db.scalar(select(exists().where(Project.workspace_id == workspace_id))))

    def list(
        self,
        organization_id: uuid.UUID,
        params: PageParams,
        *,
        search: str | None = None,
        sort: str | None = None,
    ) -> tuple[Sequence[Workspace], int]:
        # Tenant filter first; sorting and pagination only ever see this org's rows.
        stmt = select(Workspace).where(Workspace.organization_id == organization_id)
        if search:
            stmt = stmt.where(contains_ci(Workspace.name, search))
        stmt = apply_sort(stmt, sort, WORKSPACE_SORTS, "name", Workspace.id)
        return paginate(self.db, stmt, params)

    def add(self, workspace: Workspace) -> Workspace:
        self.db.add(workspace)
        self.db.flush()
        return workspace

    def delete(self, workspace: Workspace) -> None:
        self.db.delete(workspace)
        self.db.flush()
