import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        # A project's workspace must belong to the project's organization.
        ForeignKeyConstraint(
            ["workspace_id", "organization_id"],
            ["workspaces.id", "workspaces.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "name"),
        UniqueConstraint("id", "organization_id"),
    )

    # organization_id is denormalized onto every tenant-owned row so queries can
    # always filter by tenant without joining up the hierarchy.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
