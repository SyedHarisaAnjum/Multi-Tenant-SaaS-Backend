"""Rejected requests must leave data exactly as it was.

Each test: Given some state, When an unauthorized request is made, Then the API rejects
it AND a snapshot of the target row(s) is byte-for-byte unchanged.
"""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.db.models import Invitation, Membership, MembershipRole, Project, Task, Workspace
from tests.conftest import Board, Tenants
from tests.helpers import accept, create_actor, create_task, invite


def snapshot(db: Session, model: type[Any], row_id: Any) -> dict[str, Any] | None:
    """Fresh read of every column, bypassing the session's identity map."""
    db.expire_all()
    row = db.get(model, uuid.UUID(str(row_id)))
    if row is None:
        return None
    return {attr.key: getattr(row, attr.key) for attr in inspect(model).column_attrs}


def test_cross_tenant_task_update_is_rejected_and_task_unchanged(
    client: TestClient, db: Session, tenants: Tenants, globex_board: Board
) -> None:
    # Given: User A (Acme owner) and Task B owned by Organization B (Globex)
    task_b = create_task(client, tenants.mallory, globex_board.project_id, "Task B")
    before = snapshot(db, Task, task_b["id"])

    # When: User A attempts to update Task B
    response = client.patch(
        f"/api/v1/tasks/{task_b['id']}",
        json={"version": task_b["version"], "title": "pwned", "status": "in_progress"},
        headers=tenants.owner.headers,
    )

    # Then: rejected, and Task B is unchanged
    assert response.status_code == 404
    assert snapshot(db, Task, task_b["id"]) == before


def test_cross_tenant_project_update_and_delete_leave_project_unchanged(
    client: TestClient, db: Session, tenants: Tenants, globex_board: Board
) -> None:
    before = snapshot(db, Project, globex_board.project_id)
    path = f"/api/v1/projects/{globex_board.project_id}"
    assert (
        client.patch(
            path, json={"version": 1, "name": "x"}, headers=tenants.owner.headers
        ).status_code
        == 404
    )
    assert client.delete(path, headers=tenants.owner.headers).status_code == 404
    assert snapshot(db, Project, globex_board.project_id) == before


def test_unauthorized_assignment_leaves_task_unchanged(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    # Given: an Acme task; When: an Acme member assigns it to a Globex user
    task = create_task(client, tenants.member, acme_board.project_id, "Internal")
    before = snapshot(db, Task, task["id"])
    response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"version": task["version"], "assignee_id": str(tenants.mallory.id), "title": "x"},
        headers=tenants.member.headers,
    )
    # Then: rejected as a whole (the title change isn't applied either)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_MEMBER"
    assert snapshot(db, Task, task["id"]) == before


def test_viewer_update_leaves_task_unchanged(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "Read-only for viewers")
    before = snapshot(db, Task, task["id"])
    response = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"version": task["version"], "status": "in_progress"},
        headers=tenants.viewer.headers,
    )
    assert response.status_code == 403
    assert snapshot(db, Task, task["id"]) == before


def test_removed_member_token_cannot_modify_anything(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "Before removal")
    client.delete(
        f"/api/v1/organizations/{tenants.acme}/members/{tenants.member.id}",
        headers=tenants.owner.headers,
    )
    task_before = snapshot(db, Task, task["id"])
    project_before = snapshot(db, Project, acme_board.project_id)

    h = tenants.member.headers  # the removed member's still-valid access token
    assert (
        client.patch(
            f"/api/v1/tasks/{task['id']}",
            json={"version": task_before["version"], "title": "x"},
            headers=h,
        ).status_code
        == 404
    )  # type: ignore[index]
    assert client.delete(f"/api/v1/tasks/{task['id']}", headers=h).status_code == 404
    assert (
        client.patch(
            f"/api/v1/projects/{acme_board.project_id}", json={"version": 1, "name": "x"}, headers=h
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/projects/{acme_board.project_id}/tasks", json={"title": "x"}, headers=h
        ).status_code
        == 404
    )

    assert snapshot(db, Task, task["id"]) == task_before
    assert snapshot(db, Project, acme_board.project_id) == project_before
    assert db.scalar(select(Task).where(Task.title == "x")) is None


def test_role_escalation_attempts_leave_roles_unchanged(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    def roles() -> dict[uuid.UUID, MembershipRole]:
        db.expire_all()
        return dict(
            db.execute(
                select(Membership.user_id, Membership.role).where(
                    Membership.organization_id == tenants.acme
                )
            ).all()
        )

    before = roles()
    org = f"/api/v1/organizations/{tenants.acme}"
    attempts = [
        (tenants.member, "PATCH", f"{org}/members/{tenants.member.id}", {"role": "admin"}),
        (tenants.admin, "PATCH", f"{org}/members/{tenants.member.id}", {"role": "admin"}),
        (tenants.admin, "PATCH", f"{org}/members/{tenants.owner.id}", {"role": "member"}),
        (tenants.admin, "POST", f"{org}/transfer-ownership", {"user_id": str(tenants.admin.id)}),
        (tenants.viewer, "PATCH", f"{org}/members/{tenants.viewer.id}", {"role": "member"}),
    ]
    for actor, method, path, body in attempts:
        response = client.request(method, path, json=body, headers=actor.headers)
        assert response.status_code == 403, (actor.email, path, response.text)
    assert roles() == before


def test_invitation_misuse_leaves_invitation_usable_for_its_owner(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    created = invite(client, tenants.owner, tenants.acme, "bob@example.com").json()
    before = snapshot(db, Invitation, created["id"])

    # Mallory obtained Bob's link.
    stolen = accept(client, tenants.mallory, created["token"])
    assert stolen.status_code == 403
    assert snapshot(db, Invitation, created["id"]) == before  # still pending, not consumed
    assert (
        db.scalar(
            select(Membership).where(
                Membership.organization_id == tenants.acme, Membership.user_id == tenants.mallory.id
            )
        )
        is None
    )

    bob = create_actor(client, "bob@example.com")
    assert accept(client, bob, created["token"]).status_code == 200


def test_member_cannot_delete_workspace_and_it_survives(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    before = snapshot(db, Workspace, acme_board.workspace_id)
    response = client.delete(
        f"/api/v1/organizations/{tenants.acme}/workspaces/{acme_board.workspace_id}",
        headers=tenants.member.headers,
    )
    assert response.status_code == 403
    assert snapshot(db, Workspace, acme_board.workspace_id) == before
