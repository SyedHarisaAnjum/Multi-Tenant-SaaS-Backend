"""Every sensitive action × every role, in one table.

Expected codes: 2xx allowed, 403 member without the role, 404 outsider (can't even
see the organization). Each cell runs in its own rolled-back transaction.
"""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Board, Tenants
from tests.helpers import Actor, create_task

Action = Callable[[TestClient, Tenants, Board, Actor], Any]
ORG = "/api/v1/organizations/{org}"


def _org(t: Tenants) -> str:
    return ORG.format(org=t.acme)


def update_settings(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.patch(_org(t), json={"name": "Renamed"}, headers=a.headers)


def view_members(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.get(f"{_org(t)}/members", headers=a.headers)


def invite_member(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.post(f"{_org(t)}/invitations", json={"email": "n@example.com"}, headers=a.headers)


def invite_admin(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    body = {"email": "n@example.com", "role": "admin"}
    return c.post(f"{_org(t)}/invitations", json=body, headers=a.headers)


def promote_viewer(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.patch(f"{_org(t)}/members/{t.viewer.id}", json={"role": "member"}, headers=a.headers)


def remove_member(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.delete(f"{_org(t)}/members/{t.member.id}", headers=a.headers)


def transfer_ownership(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.post(
        f"{_org(t)}/transfer-ownership", json={"user_id": str(t.viewer.id)}, headers=a.headers
    )


def create_workspace(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.post(f"{_org(t)}/workspaces", json={"name": "W", "slug": "w-new"}, headers=a.headers)


def delete_workspace(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    empty = c.post(
        f"{_org(t)}/workspaces", json={"name": "E", "slug": "empty"}, headers=t.owner.headers
    ).json()
    return c.delete(f"{_org(t)}/workspaces/{empty['id']}", headers=a.headers)


def create_project(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    body = {"workspace_id": b.workspace_id, "name": "New project"}
    return c.post(f"{_org(t)}/projects", json=body, headers=a.headers)


def update_project(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.patch(
        f"/api/v1/projects/{b.project_id}", json={"version": 1, "name": "N"}, headers=a.headers
    )


def delete_project(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.delete(f"/api/v1/projects/{b.project_id}", headers=a.headers)


def create_task_action(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.post(f"/api/v1/projects/{b.project_id}/tasks", json={"title": "T"}, headers=a.headers)


def update_task(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    task = create_task(c, t.owner, b.project_id, "T")
    return c.patch(
        f"/api/v1/tasks/{task['id']}", json={"version": 1, "title": "U"}, headers=a.headers
    )


def delete_others_task(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    task = create_task(c, t.owner, b.project_id, "Owner's task")
    return c.delete(f"/api/v1/tasks/{task['id']}", headers=a.headers)


def read_summary(c: TestClient, t: Tenants, b: Board, a: Actor) -> Any:
    return c.get(f"{_org(t)}/summary", headers=a.headers)


ROLES = ("owner", "admin", "member", "viewer", "outsider")

#                         owner admin member viewer outsider
MATRIX: dict[Action, tuple[int, int, int, int, int]] = {
    read_summary:          (200, 200, 200, 200, 404),
    view_members:          (200, 200, 200, 200, 404),
    update_settings:       (200, 200, 403, 403, 404),
    invite_member:         (201, 201, 403, 403, 404),
    invite_admin:          (201, 403, 403, 403, 404),
    promote_viewer:        (200, 200, 403, 403, 404),
    # member removing themselves is "leaving", which is allowed
    remove_member:         (204, 204, 204, 403, 404),
    transfer_ownership:    (204, 403, 403, 403, 404),
    create_workspace:      (201, 201, 403, 403, 404),
    delete_workspace:      (204, 204, 403, 403, 404),
    create_project:        (201, 201, 201, 403, 404),
    update_project:        (200, 200, 200, 403, 404),
    delete_project:        (204, 204, 403, 403, 404),
    create_task_action:    (201, 201, 201, 403, 404),
    update_task:           (200, 200, 200, 403, 404),
    delete_others_task:    (204, 204, 403, 403, 404),
}  # fmt: skip

CASES = [
    pytest.param(action, role, expected[i], id=f"{action.__name__}-{role}")
    for action, expected in MATRIX.items()
    for i, role in enumerate(ROLES)
]


@pytest.mark.parametrize(("action", "role", "expected"), CASES)
def test_permission_matrix(
    client: TestClient,
    tenants: Tenants,
    acme_board: Board,
    action: Action,
    role: str,
    expected: int,
) -> None:
    actor = tenants.mallory if role == "outsider" else getattr(tenants, role)
    response = action(client, tenants, acme_board, actor)
    assert response.status_code == expected, response.text
