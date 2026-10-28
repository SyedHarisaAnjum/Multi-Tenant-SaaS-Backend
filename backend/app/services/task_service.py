import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core import cache
from app.core.exceptions import PermissionDeniedError, UnprocessableError
from app.core.permissions import MANAGER_ROLES
from app.db.models import Membership, Project, Task, TaskStatus
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services.project_service import ensure_version

# Workflow: work goes todo → in_progress → in_review → done. It can step back for
# rework, skip review, and be reopened from done. Anything else is rejected.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.IN_REVIEW, TaskStatus.DONE}),
    TaskStatus.IN_REVIEW: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.DONE}),
    TaskStatus.DONE: frozenset({TaskStatus.IN_PROGRESS}),
}


def ensure_transition_allowed(current: TaskStatus, new: TaskStatus) -> None:
    if new is not current and new not in ALLOWED_TRANSITIONS[current]:
        allowed = sorted(s.value for s in ALLOWED_TRANSITIONS[current])
        raise UnprocessableError(
            f"Can't move a task from '{current.value}' to '{new.value}'.",
            code="INVALID_STATUS_TRANSITION",
            details=[{"field": "body.status", "allowed": allowed}],
        )


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.tasks = TaskRepository(db)
        self.activity = ActivityLogRepository(db)

    def create(self, actor: Membership, project: Project, data: TaskCreate) -> Task:
        # `project` was loaded through the caller's membership, so it is in their org.
        if data.assignee_id is not None:
            self._ensure_assignable(actor, data.assignee_id)
        task = self.tasks.add(
            Task(
                organization_id=project.organization_id,
                project_id=project.id,
                title=data.title,
                description=data.description,
                status=data.status,
                priority=data.priority,
                assignee_id=data.assignee_id,
                due_date=data.due_date,
                created_by_id=actor.user_id,
            )
        )
        self._log(actor, "task.created", task, {"title": task.title})
        self.db.commit()
        self._invalidate(actor)
        return task

    def update(self, actor: Membership, task: Task, data: TaskUpdate) -> Task:
        ensure_version(task.version, data.version)
        changes = {
            k: v for k, v in data.changes().items() if k != "version" and getattr(task, k) != v
        }
        if not changes:
            return task
        if "status" in changes:
            ensure_transition_allowed(task.status, changes["status"])
        if changes.get("assignee_id") is not None:
            self._ensure_assignable(actor, changes["assignee_id"])

        details: dict[str, Any] = {"fields": sorted(changes)}
        if "status" in changes:
            details["status"] = {"from": task.status.value, "to": changes["status"].value}
        if "assignee_id" in changes:
            new_assignee = changes["assignee_id"]
            details["assignee"] = {
                "from": str(task.assignee_id) if task.assignee_id else None,
                "to": str(new_assignee) if new_assignee else None,
            }
        for field, value in changes.items():
            setattr(task, field, value)
        self._log(actor, "task.updated", task, details)
        self.db.commit()  # UPDATE ... WHERE version = :read_version (StaleDataError → 409)
        self.db.refresh(task)
        self._invalidate(actor)
        return task

    def delete(self, actor: Membership, task: Task) -> None:
        if actor.role not in MANAGER_ROLES and task.created_by_id != actor.user_id:
            raise PermissionDeniedError("Only the task's creator or an admin can delete it.")
        self._log(actor, "task.deleted", task, {"title": task.title})
        self.tasks.delete(task)
        self.db.commit()
        self._invalidate(actor)

    def _ensure_assignable(self, actor: Membership, user_id: uuid.UUID) -> None:
        if self.tasks.get_active_member_for_share(actor.organization_id, user_id) is None:
            raise UnprocessableError(
                "The assignee must be an active member of this organization.",
                code="ASSIGNEE_NOT_MEMBER",
                details=[{"field": "body.assignee_id"}],
            )

    def _log(self, actor: Membership, action: str, task: Task, details: dict[str, Any]) -> None:
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action=action,
            entity_type="task",
            entity_id=task.id,
            details={"project_id": str(task.project_id), **details},
        )

    @staticmethod
    def _invalidate(actor: Membership) -> None:
        cache.get_cache().invalidate(actor.organization_id, cache.SUMMARY)
