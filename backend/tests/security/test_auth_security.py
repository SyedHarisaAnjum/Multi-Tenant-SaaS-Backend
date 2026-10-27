from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.db.models import RefreshToken, User
from tests.helpers import auth_header, login, post_with_refresh_token, refresh_cookie, register


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": "Basic YWxpY2U6cGFzcw=="},
    ],
)
def test_protected_endpoint_rejects_missing_or_malformed_credentials(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_access_token_is_rejected(client: TestClient, db: Session) -> None:
    register(client)
    user = db.scalar(select(User))
    assert user is not None
    stale = datetime.now(timezone.utc) - timedelta(
        minutes=get_settings().access_token_expire_minutes + 1
    )
    token = security.create_access_token(user.id, now=stale)
    assert client.get("/api/v1/auth/me", headers=auth_header(token)).status_code == 401


def test_access_token_of_deactivated_user_is_rejected(client: TestClient, db: Session) -> None:
    register(client)
    token = login(client).json()["access_token"]
    user = db.scalar(select(User))
    assert user is not None
    user.is_active = False
    db.flush()
    assert client.get("/api/v1/auth/me", headers=auth_header(token)).status_code == 401


def test_deactivated_user_cannot_log_in(client: TestClient, db: Session) -> None:
    register(client)
    user = db.scalar(select(User))
    assert user is not None
    user.is_active = False
    db.flush()
    assert login(client).status_code == 401


def test_refresh_tokens_are_stored_only_as_hashes(client: TestClient, db: Session) -> None:
    register(client)
    raw = refresh_cookie(login(client))
    stored = db.scalars(select(RefreshToken.token_hash)).all()
    assert raw not in stored
    assert security.hash_refresh_token(raw) in stored


def test_refresh_token_reuse_revokes_whole_session(client: TestClient) -> None:
    register(client)
    original = refresh_cookie(login(client))
    successor = refresh_cookie(post_with_refresh_token(client, "/api/v1/auth/refresh", original))

    # Attacker replays the rotated-out token...
    assert post_with_refresh_token(client, "/api/v1/auth/refresh", original).status_code == 401
    # ...which also kills the legitimate successor, forcing a fresh login.
    assert post_with_refresh_token(client, "/api/v1/auth/refresh", successor).status_code == 401


def test_logout_only_revokes_its_own_session(client: TestClient) -> None:
    register(client)
    laptop = refresh_cookie(login(client))
    phone = refresh_cookie(login(client))

    post_with_refresh_token(client, "/api/v1/auth/logout", laptop)

    assert post_with_refresh_token(client, "/api/v1/auth/refresh", laptop).status_code == 401
    assert post_with_refresh_token(client, "/api/v1/auth/refresh", phone).status_code == 200


def test_expired_refresh_token_is_rejected(client: TestClient, db: Session) -> None:
    register(client)
    raw = refresh_cookie(login(client))
    stored = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == security.hash_refresh_token(raw))
    )
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()
    assert post_with_refresh_token(client, "/api/v1/auth/refresh", raw).status_code == 401


def test_forged_refresh_token_is_rejected(client: TestClient) -> None:
    response = post_with_refresh_token(
        client, "/api/v1/auth/refresh", security.generate_refresh_token()
    )
    assert response.status_code == 401
