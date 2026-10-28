import uuid
from datetime import date, datetime
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.db.models import TaskPriority, TaskStatus
from app.schemas.common import PartialUpdate, RequestModel
from app.schemas.projects import Description, Version

TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class TaskCreate(RequestModel):
    title: TaskTitle
    description: Description | None = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None


class TaskUpdate(PartialUpdate):
    """Covers editing, assignment (`assignee_id`, null to unassign), status transitions
    and due-date changes. Enum fields reject anything outside the allowed values."""

    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"description", "assignee_id", "due_date"}
    )

    version: Version
    title: TaskTitle | None = None
    description: Description | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    assignee_id: uuid.UUID | None
    created_by_id: uuid.UUID | None
    due_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime
