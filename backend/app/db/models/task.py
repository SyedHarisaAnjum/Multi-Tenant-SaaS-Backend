import enum
import uuid
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


def _str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # A task's project must belong to the task's organization.
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_tasks_organization_id_project_id_status", "organization_id", "project_id", "status"
        ),
        Index("ix_tasks_assignee_id", "assignee_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(
        _str_enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.TODO
    )
    priority: Mapped[TaskPriority] = mapped_column(
        _str_enum(TaskPriority, "task_priority"), nullable=False, default=TaskPriority.MEDIUM
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
