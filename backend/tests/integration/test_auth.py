from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from tests.helpers import (
    PASSWORD,
    auth_header,
    login,
    post_with_refresh_token,
    refresh_cookie,
    register,
)


def test_register_creates_user_without_leaking_hash(client: TestClient, db: Session) -> None:
    response = register(client, email="  Alice@Example.com ")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body and "password_hash" not in body

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


def test_register_duplicate_email_is_case_insensitive(client: TestClient) -> None:
    assert register(client, email="bob@example.com").status_code == 201
    response = register(client, email="BOB@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_register_rejects_weak_password(client: TestClient) -> None:
    assert register(client, password="short").status_code == 422


def test_login_returns_access_token_and_httponly_refresh_cookie(client: TestClient) -> None:
    register(client)
    response = login(client, email="ALICE@example.com")
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_expire_minutes * 60
    assert "refresh_token" not in body
    assert response.headers["cache-control"] == "no-store"

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    register(client)
    response = login(client, password="not the right password")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_login_with_unknown_email_gives_same_error(client: TestClient) -> None:
    register(client)
    wrong_password = login(client, password="not the right password")
    unknown_user = login(client, email="nobody@example.com")
    assert unknown_user.status_code == 401
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(unknown_user) == strip(wrong_password)


def test_me_returns_current_user(client: TestClient) -> None:
    register(client)
    token = login(client).json()["access_token"]
    response = client.get("/api/v1/auth/me", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_refresh_rotates_tokens(client: TestClient) -> None:
    register(client)
    first = login(client)
    first_refresh = refresh_cookie(first)

    response = post_with_refresh_token(client, "/api/v1/auth/refresh", first_refresh)
    assert response.status_code == 200
    second_refresh = refresh_cookie(response)
    assert second_refresh != first_refresh

    new_access = response.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=auth_header(new_access)).status_code == 200

    # The successor can itself be rotated.
    assert (
        post_with_refresh_token(client, "/api/v1/auth/refresh", second_refresh).status_code == 200
    )


def test_refresh_without_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh_session(client: TestClient) -> None:
    register(client)
    token = refresh_cookie(login(client))

    response = post_with_refresh_token(client, "/api/v1/auth/logout", token)
    assert response.status_code == 204
    assert 'refresh_token=""' in response.headers["set-cookie"] or "max-age=0" in (
        response.headers["set-cookie"].lower()
    )

    assert post_with_refresh_token(client, "/api/v1/auth/refresh", token).status_code == 401


def test_logout_is_idempotent(client: TestClient) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert post_with_refresh_token(client, "/api/v1/auth/logout", "unknown").status_code == 204
