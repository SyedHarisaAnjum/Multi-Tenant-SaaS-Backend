import enum
import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        # A project's workspace must belong to the project's organization.
        # RESTRICT: a workspace can't be deleted while it still has projects.
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.id", "workspaces.organization_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workspace_id", "name"),
        UniqueConstraint("id", "organization_id"),
        Index("ix_projects_organization_id_created_at", "organization_id", "created_at"),
        # Trigram index so `name ILIKE '%term%'` search doesn't scan the table.
        Index(
            "ix_projects_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    # organization_id is denormalized onto every tenant-owned row so queries can
    # always filter by tenant without joining up the hierarchy.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        str_enum(ProjectStatus, "project_status"),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default=ProjectStatus.ACTIVE.value,
    )
    # Optimistic locking: SQLAlchemy adds `AND version = :expected` to every UPDATE
    # and bumps it, so a concurrent writer's save fails instead of being overwritten.
    version: Mapped[int] = mapped_column(nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version}
