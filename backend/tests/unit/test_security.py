import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core import security
from app.core.config import get_settings


def test_hash_password_uses_argon2id_and_is_salted() -> None:
    first = security.hash_password("s3cret-password!")
    second = security.hash_password("s3cret-password!")
    assert first.startswith("$argon2id$")
    assert first != second
    assert "s3cret-password!" not in first


def test_verify_password() -> None:
    hashed = security.hash_password("s3cret-password!")
    assert security.verify_password("s3cret-password!", hashed)
    assert not security.verify_password("wrong-password!!", hashed)


def test_verify_password_without_hash_is_false() -> None:
    assert not security.verify_password("anything", None)


def test_verify_password_with_garbage_hash_is_false() -> None:
    assert not security.verify_password("anything", "not-a-hash")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    assert security.decode_access_token(security.create_access_token(user_id)) == user_id


def test_expired_access_token_is_rejected() -> None:
    issued = datetime.now(timezone.utc) - timedelta(
        minutes=get_settings().access_token_expire_minutes + 1
    )
    token = security.create_access_token(uuid.uuid4(), now=issued)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_access_token_signed_with_other_key_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        "a-completely-different-secret-key-of-enough-length",
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_unsigned_alg_none_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        key=None,
        algorithm="none",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_token_with_wrong_type_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        get_settings().jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_refresh_tokens_are_random_and_hash_deterministically() -> None:
    a, b = security.generate_refresh_token(), security.generate_refresh_token()
    assert a != b
    assert len(a) >= 64
    assert security.hash_refresh_token(a) == security.hash_refresh_token(a)
    assert security.hash_refresh_token(a) != a
