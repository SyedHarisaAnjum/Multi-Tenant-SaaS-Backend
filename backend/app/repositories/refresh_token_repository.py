import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_hash_for_update(self, token_hash: str) -> RefreshToken | None:
        # Row lock serializes concurrent refreshes of the same token, so only
        # one can rotate it; the other sees it revoked.
        return self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )

    def add(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        return token

    def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
