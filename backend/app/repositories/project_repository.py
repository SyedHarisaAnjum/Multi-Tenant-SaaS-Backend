import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectStatus
from app.dependencies.pagination import PageParams
from app.repositories.query_utils import apply_sort, contains_ci, paginate

PROJECT_SORTS = {
    "name": Project.name,
    "status": Project.status,
    "created_at": Project.created_at,
    "updated_at": Project.updated_at,
}


@dataclass(frozen=True)
class ProjectFilters:
    workspace_id: uuid.UUID | None = None
    status: ProjectStatus | None = None
    search: str | None = None


class ProjectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def name_taken(
        self, workspace_id: uuid.UUID, name: str, exclude_id: uuid.UUID | None = None
    ) -> bool:
        stmt = select(Project.id).where(Project.workspace_id == workspace_id, Project.name == name)
        if exclude_id is not None:
            stmt = stmt.where(Project.id != exclude_id)
        return self.db.scalar(stmt) is not None

    def list(
        self,
        organization_id: uuid.UUID,
        params: PageParams,
        filters: ProjectFilters,
        sort: str | None = None,
    ) -> tuple[Sequence[Project], int]:
        stmt = select(Project).where(Project.organization_id == organization_id)
        if filters.workspace_id is not None:
            stmt = stmt.where(Project.workspace_id == filters.workspace_id)
        if filters.status is not None:
            stmt = stmt.where(Project.status == filters.status)
        if filters.search:
            stmt = stmt.where(contains_ci(Project.name, filters.search))
        stmt = apply_sort(stmt, sort, PROJECT_SORTS, "-created_at", Project.id)
        return paginate(self.db, stmt, params)

    def add(self, project: Project) -> Project:
        self.db.add(project)
        self.db.flush()
        return project

    def delete(self, project: Project) -> None:
        self.db.delete(project)
        self.db.flush()
