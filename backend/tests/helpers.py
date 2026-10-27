from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import get_settings

PASSWORD = "correct horse battery staple"


def register(
    client: TestClient, email: str = "alice@example.com", password: str = PASSWORD
) -> Response:
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def login(
    client: TestClient, email: str = "alice@example.com", password: str = PASSWORD
) -> Response:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def refresh_cookie(response: Response) -> str:
    value = response.cookies.get(get_settings().refresh_cookie_name)
    assert value, "response did not set a refresh cookie"
    return value


def post_with_refresh_token(client: TestClient, path: str, token: str) -> Response:
    """Send an explicit refresh token, bypassing whatever the client's cookie jar holds."""
    client.cookies.clear()
    return client.post(path, headers={"Cookie": f"{get_settings().refresh_cookie_name}={token}"})


def auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
