"""Import every model here so Base.metadata is complete for Alembic autogenerate."""

from app.db.models.activity_log import ActivityLog
from app.db.models.invitation import Invitation
from app.db.models.organization import Membership, MembershipRole, Organization
from app.db.models.project import Project, ProjectStatus
from app.db.models.refresh_token import RefreshToken
from app.db.models.task import Task, TaskPriority, TaskStatus
from app.db.models.user import User
from app.db.models.workspace import Workspace

__all__ = [
    "ActivityLog",
    "Invitation",
    "Membership",
    "MembershipRole",
    "Organization",
    "Project",
    "ProjectStatus",
    "RefreshToken",
    "Task",
    "TaskPriority",
    "TaskStatus",
    "User",
    "Workspace",
]
