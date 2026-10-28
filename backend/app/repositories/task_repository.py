import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import CursorResult, case, func, select, update
from sqlalchemy.orm import Session

from app.db.models import Membership, Task, TaskPriority, TaskStatus, User
from app.dependencies.pagination import PageParams
from app.repositories.query_utils import apply_sort, contains_ci, paginate

# Sort priority by severity, not alphabetically.
_PRIORITY_RANK = case(
    {
        TaskPriority.LOW: 0,
        TaskPriority.MEDIUM: 1,
        TaskPriority.HIGH: 2,
        TaskPriority.URGENT: 3,
    },
    value=Task.priority,
)
TASK_SORTS = {
    "title": Task.title,
    "status": Task.status,
    "priority": _PRIORITY_RANK,
    "due_date": Task.due_date,
    "created_at": Task.created_at,
    "updated_at": Task.updated_at,
}


@dataclass(frozen=True)
class TaskFilters:
    project_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_before: date | None = None
    due_after: date | None = None
    search: str | None = None


class TaskRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        organization_id: uuid.UUID,
        params: PageParams,
        filters: TaskFilters,
        sort: str | None = None,
    ) -> tuple[Sequence[Task], int]:
        # Tenant filter is unconditional and comes first; every other filter narrows it.
        stmt = select(Task).where(Task.organization_id == organization_id)
        if filters.project_id is not None:
            stmt = stmt.where(Task.project_id == filters.project_id)
        if filters.assignee_id is not None:
            stmt = stmt.where(Task.assignee_id == filters.assignee_id)
        if filters.status is not None:
            stmt = stmt.where(Task.status == filters.status)
        if filters.priority is not None:
            stmt = stmt.where(Task.priority == filters.priority)
        if filters.due_before is not None:
            stmt = stmt.where(Task.due_date <= filters.due_before)
        if filters.due_after is not None:
            stmt = stmt.where(Task.due_date >= filters.due_after)
        if filters.search:
            stmt = stmt.where(contains_ci(Task.title, filters.search))
        stmt = apply_sort(stmt, sort, TASK_SORTS, "-created_at", Task.id)
        return paginate(self.db, stmt, params)

    def get_active_member_for_share(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership | None:
        """The user's membership if they are an active member, locked FOR SHARE.

        The share lock makes a concurrent removal of this member wait until we commit,
        so the removal's "unassign their tasks" step is guaranteed to see our assignment.
        """
        return self.db.scalar(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
                User.is_active.is_(True),
            )
            .with_for_update(read=True, of=Membership)
        )

    def unassign_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Clear a removed member's assignments in one organization. Returns rows changed."""
        result: CursorResult[Any] = self.db.execute(  # type: ignore[assignment]
            update(Task)
            .where(Task.organization_id == organization_id, Task.assignee_id == user_id)
            # Bulk UPDATEs bypass the ORM version counter; bump it so clients holding
            # the old version get a conflict instead of silently re-assigning.
            .values(assignee_id=None, version=Task.version + 1, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
        return result.rowcount

    def add(self, task: Task) -> Task:
        self.db.add(task)
        self.db.flush()
        return task

    def delete(self, task: Task) -> None:
        self.db.delete(task)
        self.db.flush()
