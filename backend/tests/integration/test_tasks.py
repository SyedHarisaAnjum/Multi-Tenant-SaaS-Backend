import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActivityLog, Task, User
from tests.conftest import Board, Tenants
from tests.helpers import create_task


def _patch(client: TestClient, actor: Any, task: dict[str, Any], **changes: Any) -> Any:
    return client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"version": task["version"], **changes},
        headers=actor.headers,
    )


# --- create ---------------------------------------------------------------------


def test_create_task_with_all_fields(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    due = (date.today() + timedelta(days=7)).isoformat()
    task = create_task(
        client,
        tenants.member,
        acme_board.project_id,
        "  Write docs ",
        description="All of them",
        priority="high",
        assignee_id=str(tenants.viewer.id),
        due_date=due,
    )
    assert task["title"] == "Write docs"
    assert task["status"] == "todo"
    assert task["priority"] == "high"
    assert task["assignee_id"] == str(tenants.viewer.id)
    assert task["created_by_id"] == str(tenants.member.id)
    assert task["due_date"] == due
    assert task["organization_id"] == str(tenants.acme)
    assert task["created_at"] and task["updated_at"]


def test_viewer_cannot_create_task(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    response = client.post(
        f"/api/v1/projects/{acme_board.project_id}/tasks",
        json={"title": "x"},
        headers=tenants.viewer.headers,
    )
    assert response.status_code == 403


def test_cannot_create_task_in_other_orgs_project(
    client: TestClient, db: Session, tenants: Tenants, globex_board: Board
) -> None:
    response = client.post(
        f"/api/v1/projects/{globex_board.project_id}/tasks",
        json={"title": "Planted"},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 404
    assert db.scalar(select(Task).where(Task.title == "Planted")) is None


@pytest.mark.parametrize(
    "body",
    [
        {"title": ""},
        {"title": "x", "status": "blocked"},
        {"title": "x", "priority": "critical"},
        {"title": "x", "due_date": "next tuesday"},
        {"title": "x", "organization_id": str(uuid.uuid4())},
    ],
)
def test_task_create_validation(
    client: TestClient, tenants: Tenants, acme_board: Board, body: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/projects/{acme_board.project_id}/tasks", json=body, headers=tenants.member.headers
    )
    assert response.status_code == 422


# --- assignment -----------------------------------------------------------------


def test_assign_and_unassign(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "Assign me")
    assigned = _patch(client, tenants.member, task, assignee_id=str(tenants.admin.id))
    assert assigned.status_code == 200
    assert assigned.json()["assignee_id"] == str(tenants.admin.id)

    cleared = _patch(client, tenants.member, assigned.json(), assignee_id=None)
    assert cleared.status_code == 200
    assert cleared.json()["assignee_id"] is None


@pytest.mark.parametrize("who", ["outsider", "nobody"])
def test_assignee_must_be_member(
    client: TestClient, tenants: Tenants, acme_board: Board, who: str
) -> None:
    target = tenants.mallory.id if who == "outsider" else uuid.uuid4()
    response = client.post(
        f"/api/v1/projects/{acme_board.project_id}/tasks",
        json={"title": "x", "assignee_id": str(target)},
        headers=tenants.member.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_MEMBER"


def test_assignee_must_be_active(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    viewer = db.get(User, tenants.viewer.id)
    assert viewer is not None
    viewer.is_active = False
    db.flush()
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    response = _patch(client, tenants.member, task, assignee_id=str(tenants.viewer.id))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ASSIGNEE_NOT_MEMBER"


def test_removing_member_unassigns_their_tasks(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(
        client, tenants.member, acme_board.project_id, "Mine", assignee_id=str(tenants.viewer.id)
    )
    removed = client.delete(
        f"/api/v1/organizations/{tenants.acme}/members/{tenants.viewer.id}",
        headers=tenants.admin.headers,
    )
    assert removed.status_code == 204

    after = client.get(f"/api/v1/tasks/{task['id']}", headers=tenants.member.headers).json()
    assert after["assignee_id"] is None
    assert after["version"] == task["version"] + 1  # holders of the old version get a 409
    log = db.scalar(select(ActivityLog).where(ActivityLog.action == "member.removed"))
    assert log is not None and log.details["tasks_unassigned"] == 1


# --- status transitions, priority, due date -------------------------------------


def test_status_workflow(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "Flow")
    for status in ("in_progress", "in_review", "done", "in_progress"):  # last one = reopen
        response = _patch(client, tenants.member, task, status=status)
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["status"] == status


@pytest.mark.parametrize(
    ("start", "target"), [((), "done"), ((), "in_review"), (("in_progress", "done"), "todo")]
)
def test_invalid_status_transitions(
    client: TestClient, tenants: Tenants, acme_board: Board, start: tuple[str, ...], target: str
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "Flow")
    for status in start:
        task = _patch(client, tenants.member, task, status=status).json()
    response = _patch(client, tenants.member, task, status=target)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert "allowed" in response.json()["error"]["details"][0]


@pytest.mark.parametrize("field", ["status", "priority"])
def test_enum_fields_reject_arbitrary_strings(
    client: TestClient, tenants: Tenants, acme_board: Board, field: str
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    response = _patch(client, tenants.member, task, **{field: "whatever"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_due_date_update_and_clear(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    updated = _patch(client, tenants.member, task, due_date="2030-01-31", priority="urgent").json()
    assert (updated["due_date"], updated["priority"]) == ("2030-01-31", "urgent")
    cleared = _patch(client, tenants.member, updated, due_date=None).json()
    assert cleared["due_date"] is None


def test_title_cannot_be_nulled(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    assert _patch(client, tenants.member, task, title=None).status_code == 422


def test_concurrent_edit_conflict(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    assert _patch(client, tenants.member, task, title="mine").status_code == 200
    stale = _patch(client, tenants.admin, task, title="theirs")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_noop_update_keeps_version(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "same")
    response = _patch(client, tenants.member, task, title="same")
    assert response.json()["version"] == task["version"]


def test_updates_are_audited(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    _patch(client, tenants.member, task, status="in_progress", assignee_id=str(tenants.admin.id))
    log = db.scalar(select(ActivityLog).where(ActivityLog.action == "task.updated"))
    assert log is not None
    assert log.details["status"] == {"from": "todo", "to": "in_progress"}
    assert log.details["assignee"] == {"from": None, "to": str(tenants.admin.id)}


# --- delete ---------------------------------------------------------------------


def test_creator_can_delete_own_task(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    assert (
        client.delete(f"/api/v1/tasks/{task['id']}", headers=tenants.member.headers).status_code
        == 204
    )
    assert (
        client.get(f"/api/v1/tasks/{task['id']}", headers=tenants.member.headers).status_code == 404
    )


def test_member_cannot_delete_others_task(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    task = create_task(client, tenants.admin, acme_board.project_id, "x")
    other_member = client.delete(f"/api/v1/tasks/{task['id']}", headers=tenants.member.headers)
    assert other_member.status_code == 403
    viewer = client.delete(f"/api/v1/tasks/{task['id']}", headers=tenants.viewer.headers)
    assert viewer.status_code == 403


def test_admin_can_delete_any_task(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    task = create_task(client, tenants.member, acme_board.project_id, "x")
    assert (
        client.delete(f"/api/v1/tasks/{task['id']}", headers=tenants.admin.headers).status_code
        == 204
    )


# --- cross-tenant ---------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_cannot_touch_other_orgs_task(
    client: TestClient, db: Session, tenants: Tenants, globex_board: Board, method: str
) -> None:
    task = create_task(client, tenants.mallory, globex_board.project_id, "Globex secret")
    body = {"version": task["version"], "title": "Pwned"} if method == "PATCH" else None
    response = client.request(
        method, f"/api/v1/tasks/{task['id']}", json=body, headers=tenants.owner.headers
    )
    assert response.status_code == 404
    db.expire_all()
    stored = db.get(Task, uuid.UUID(task["id"]))
    assert stored is not None and stored.title == "Globex secret"


def test_cannot_list_other_orgs_project_tasks(
    client: TestClient, tenants: Tenants, globex_board: Board
) -> None:
    response = client.get(
        f"/api/v1/projects/{globex_board.project_id}/tasks", headers=tenants.owner.headers
    )
    assert response.status_code == 404


# --- listing --------------------------------------------------------------------


@pytest.fixture
def task_set(client: TestClient, tenants: Tenants, acme_board: Board) -> dict[str, Any]:
    today = date.today()
    specs = [
        ("Fix login bug", "high", tenants.member, today - timedelta(days=1)),
        ("Write release notes", "low", tenants.admin, today + timedelta(days=3)),
        ("Urgent hotfix", "urgent", tenants.member, None),
        ("Refactor login form", "medium", None, today + timedelta(days=10)),
    ]
    tasks = {}
    for title, priority, assignee, due in specs:
        tasks[title] = create_task(
            client,
            tenants.member,
            acme_board.project_id,
            title,
            priority=priority,
            assignee_id=str(assignee.id) if assignee else None,
            due_date=due.isoformat() if due else None,
        )
    _patch(client, tenants.member, tasks["Fix login bug"], status="in_progress")
    return tasks


def _titles(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [t["title"] for t in response.json()["items"]]


def test_list_by_project_with_filters(
    client: TestClient, tenants: Tenants, acme_board: Board, task_set: dict[str, Any]
) -> None:
    path = f"/api/v1/projects/{acme_board.project_id}/tasks"
    h = tenants.viewer.headers
    assert _titles(client.get(path, params={"status": "in_progress"}, headers=h)) == [
        "Fix login bug"
    ]
    assert _titles(client.get(path, params={"priority": "urgent"}, headers=h)) == ["Urgent hotfix"]
    assert sorted(_titles(client.get(path, params={"q": "LOGIN"}, headers=h))) == [
        "Fix login bug",
        "Refactor login form",
    ]
    due_soon = client.get(path, params={"due_before": date.today().isoformat()}, headers=h)
    assert _titles(due_soon) == ["Fix login bug"]


def test_sort_by_priority_uses_severity_not_alphabet(
    client: TestClient, tenants: Tenants, acme_board: Board, task_set: dict[str, Any]
) -> None:
    response = client.get(
        f"/api/v1/projects/{acme_board.project_id}/tasks",
        params={"sort": "-priority"},
        headers=tenants.viewer.headers,
    )
    assert _titles(response) == [
        "Urgent hotfix",
        "Fix login bug",
        "Refactor login form",
        "Write release notes",
    ]


def test_sort_by_due_date_puts_undated_last(
    client: TestClient, tenants: Tenants, acme_board: Board, task_set: dict[str, Any]
) -> None:
    response = client.get(
        f"/api/v1/projects/{acme_board.project_id}/tasks",
        params={"sort": "due_date"},
        headers=tenants.viewer.headers,
    )
    assert _titles(response)[-1] == "Urgent hotfix"


def test_list_by_assignee(
    client: TestClient, tenants: Tenants, acme_board: Board, task_set: dict[str, Any]
) -> None:
    path = f"/api/v1/organizations/{tenants.acme}/tasks"
    by_id = client.get(
        path,
        params={"assignee_id": str(tenants.member.id), "sort": "title"},
        headers=tenants.owner.headers,
    )
    assert _titles(by_id) == ["Fix login bug", "Urgent hotfix"]
    mine = client.get(path, params={"assigned_to_me": True}, headers=tenants.admin.headers)
    assert _titles(mine) == ["Write release notes"]


def test_org_task_list_excludes_other_tenants(
    client: TestClient, tenants: Tenants, globex_board: Board, task_set: dict[str, Any]
) -> None:
    create_task(client, tenants.mallory, globex_board.project_id, "Globex task")
    response = client.get(
        f"/api/v1/organizations/{tenants.acme}/tasks",
        params={"page_size": 100},
        headers=tenants.owner.headers,
    )
    assert response.json()["total"] == 4
    assert "Globex task" not in _titles(response)
    outsider = client.get(
        f"/api/v1/organizations/{tenants.acme}/tasks", headers=tenants.mallory.headers
    )
    assert outsider.status_code == 404
