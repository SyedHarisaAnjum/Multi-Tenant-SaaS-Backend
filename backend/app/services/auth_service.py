import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.db.models import RefreshToken, User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.refresh_tokens = RefreshTokenRepository(db)

    def register(self, data: RegisterRequest) -> User:
        if self.users.get_by_email(data.email):
            raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")
        user = User(
            email=data.email,
            password_hash=security.hash_password(data.password),
            full_name=data.full_name,
        )
        try:
            self.users.add(user)
            self.db.commit()
        except IntegrityError:
            # Lost a race with a concurrent registration for the same email.
            self.db.rollback()
            raise ConflictError(
                "An account with this email already exists.", code="EMAIL_TAKEN"
            ) from None
        return user

    def login(self, data: LoginRequest) -> IssuedTokens:
        user = self.users.get_by_email(data.email)
        # Always run verification, even for unknown emails, to keep timing uniform.
        password_ok = security.verify_password(data.password, user.password_hash if user else None)
        if user is None or not password_ok or not user.is_active:
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")

        if security.password_needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(data.password)

        tokens, _ = self._issue_tokens(user.id, family_id=uuid.uuid4())
        self.db.commit()
        return tokens

    def refresh(self, raw_refresh_token: str | None) -> IssuedTokens:
        if not raw_refresh_token:
            raise AuthenticationError("Missing refresh token.", code="INVALID_REFRESH_TOKEN")
        now = datetime.now(timezone.utc)
        stored = self.refresh_tokens.get_by_hash_for_update(
            security.hash_opaque_token(raw_refresh_token)
        )
        if stored is None:
            raise AuthenticationError("Invalid refresh token.", code="INVALID_REFRESH_TOKEN")

        if stored.revoked_at is not None:
            # A rotated-out token was replayed: assume it was stolen and kill the session.
            logger.warning(
                "Refresh token reuse detected; revoking family %s for user %s",
                stored.family_id,
                stored.user_id,
            )
            self.refresh_tokens.revoke_family(stored.family_id, now)
            self.db.commit()
            raise AuthenticationError("Invalid refresh token.", code="INVALID_REFRESH_TOKEN")

        if stored.expires_at <= now:
            raise AuthenticationError("Refresh token expired.", code="INVALID_REFRESH_TOKEN")

        user = self.users.get(stored.user_id)
        if user is None or not user.is_active:
            self.refresh_tokens.revoke_family(stored.family_id, now)
            self.db.commit()
            raise AuthenticationError("Invalid refresh token.", code="INVALID_REFRESH_TOKEN")

        tokens, successor = self._issue_tokens(user.id, family_id=stored.family_id, now=now)
        stored.revoked_at = now
        stored.replaced_by_id = successor.id
        self.db.commit()
        return tokens

    def logout(self, raw_refresh_token: str | None) -> None:
        """Revoke the session the refresh token belongs to. Idempotent."""
        if not raw_refresh_token:
            return
        stored = self.refresh_tokens.get_by_hash_for_update(
            security.hash_opaque_token(raw_refresh_token)
        )
        if stored is not None:
            self.refresh_tokens.revoke_family(stored.family_id, datetime.now(timezone.utc))
        self.db.commit()

    def _issue_tokens(
        self, user_id: uuid.UUID, family_id: uuid.UUID, now: datetime | None = None
    ) -> tuple[IssuedTokens, RefreshToken]:
        settings = get_settings()
        now = now or datetime.now(timezone.utc)
        raw_refresh = security.generate_opaque_token()
        record = self.refresh_tokens.add(
            RefreshToken(
                user_id=user_id,
                token_hash=security.hash_opaque_token(raw_refresh),
                family_id=family_id,
                expires_at=now + timedelta(days=settings.refresh_token_expire_days),
            )
        )
        tokens = IssuedTokens(
            access_token=security.create_access_token(user_id, now=now),
            refresh_token=raw_refresh,
            expires_in=settings.access_token_expire_minutes * 60,
        )
        return tokens, record
