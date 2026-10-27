import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ActivityLog


class ActivityLogRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        organization_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Stage an audit entry; it commits (or rolls back) with the caller's transaction."""
        self.db.add(
            ActivityLog(
                organization_id=organization_id,
                actor_id=actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details or {},
            )
        )
