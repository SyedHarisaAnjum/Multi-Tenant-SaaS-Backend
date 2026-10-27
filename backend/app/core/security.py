import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# argon2-cffi defaults to Argon2id with RFC 9106 "low memory" parameters.
_password_hasher = PasswordHasher()

# Used to spend the same time verifying when the user doesn't exist,
# so login response time doesn't reveal which emails are registered.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(16))

ACCESS_TOKEN_TYPE = "access"  # noqa: S105  (a claim value, not a secret)


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _password_hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _password_hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID, now: datetime | None = None) -> str:
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id from a valid access token, else raise InvalidTokenError."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "type"]},
        )
        if payload["type"] != ACCESS_TOKEN_TYPE:
            raise InvalidTokenError("wrong token type")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def generate_refresh_token() -> str:
    """Opaque, high-entropy token. Only its hash is stored server-side."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    # The token is random with 384 bits of entropy, so a fast hash is enough;
    # a slow KDF would only matter for low-entropy secrets like passwords.
    return hashlib.sha256(token.encode()).hexdigest()
