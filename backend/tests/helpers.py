import uuid
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class Actor:
    id: uuid.UUID
    email: str
    headers: dict[str, str]


def create_actor(client: TestClient, email: str) -> Actor:
    """Register and log in a user; returns their id and bearer headers."""
    response = register(client, email=email)
    assert response.status_code == 201, response.text
    token = login(client, email=email).json()["access_token"]
    return Actor(id=uuid.UUID(response.json()["id"]), email=email, headers=auth_header(token))


def create_org(client: TestClient, owner: Actor, slug: str) -> uuid.UUID:
    response = client.post(
        "/api/v1/organizations", json={"name": slug.title(), "slug": slug}, headers=owner.headers
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def invite(
    client: TestClient, inviter: Actor, org_id: uuid.UUID, email: str, role: str = "member"
) -> Response:
    return client.post(
        f"/api/v1/organizations/{org_id}/invitations",
        json={"email": email, "role": role},
        headers=inviter.headers,
    )


def accept(client: TestClient, actor: Actor, token: str) -> Response:
    return client.post("/api/v1/invitations/accept", json={"token": token}, headers=actor.headers)


def add_member(
    client: TestClient, inviter: Actor, org_id: uuid.UUID, member: Actor, role: str
) -> None:
    created = invite(client, inviter, org_id, member.email, role)
    assert created.status_code == 201, created.text
    accepted = accept(client, member, created.json()["token"])
    assert accepted.status_code == 200, accepted.text


def create_workspace(
    client: TestClient, actor: Actor, org_id: uuid.UUID, slug: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/organizations/{org_id}/workspaces",
        json={"name": slug.replace("-", " ").title(), "slug": slug},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def create_project(
    client: TestClient,
    actor: Actor,
    org_id: uuid.UUID,
    workspace_id: str,
    name: str,
    **fields: Any,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"workspace_id": workspace_id, "name": name, **fields},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def create_task(
    client: TestClient, actor: Actor, project_id: str, title: str, **fields: Any
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project_id}/tasks",
        json={"title": title, **fields},
        headers=actor.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]
