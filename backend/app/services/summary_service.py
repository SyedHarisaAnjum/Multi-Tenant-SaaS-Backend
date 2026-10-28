import uuid

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Membership, Project, ProjectStatus, Task, TaskStatus, Workspace


class CountsByStatus(BaseModel):
    total: int
    by_status: dict[str, int]


class TaskCounts(CountsByStatus):
    overdue: int


class OrganizationSummary(BaseModel):
    """Identical for every member of the organization, which is what makes it cacheable."""

    members: int
    workspaces: int
    projects: CountsByStatus
    tasks: TaskCounts


def build_summary(db: Session, organization_id: uuid.UUID) -> OrganizationSummary:
    def count(model: type[Membership] | type[Workspace]) -> int:
        stmt = (
            select(func.count()).select_from(model).where(model.organization_id == organization_id)
        )
        return db.scalar(stmt) or 0

    project_rows = db.execute(
        select(Project.status, func.count())
        .where(Project.organization_id == organization_id)
        .group_by(Project.status)
    ).all()
    task_rows = db.execute(
        select(Task.status, func.count())
        .where(Task.organization_id == organization_id)
        .group_by(Task.status)
    ).all()
    overdue = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.organization_id == organization_id,
            Task.status != TaskStatus.DONE,
            Task.due_date < func.current_date(),
        )
    )

    projects = {s.value: 0 for s in ProjectStatus} | {s.value: n for s, n in project_rows}
    tasks = {s.value: 0 for s in TaskStatus} | {s.value: n for s, n in task_rows}
    return OrganizationSummary(
        members=count(Membership),
        workspaces=count(Workspace),
        projects=CountsByStatus(total=sum(projects.values()), by_status=projects),
        tasks=TaskCounts(total=sum(tasks.values()), by_status=tasks, overdue=overdue or 0),
    )
