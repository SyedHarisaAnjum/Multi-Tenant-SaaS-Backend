import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Task
from tests.conftest import Board, Tenants
from tests.helpers import create_project, create_task, create_workspace


def _projects(org: object) -> str:
    return f"/api/v1/organizations/{org}/projects"


# --- create ---------------------------------------------------------------------


def test_member_creates_project_with_defaults(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    response = client.post(
        _projects(tenants.acme),
        json={"workspace_id": acme_board.workspace_id, "name": "Website", "description": "v2"},
        headers=tenants.member.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["version"] == 1
    assert body["organization_id"] == str(tenants.acme)


def test_viewer_cannot_create_project(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    response = client.post(
        _projects(tenants.acme),
        json={"workspace_id": acme_board.workspace_id, "name": "X"},
        headers=tenants.viewer.headers,
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},  # missing name
        {"name": "   "},  # blank after trimming
        {"name": "X", "status": "deleted"},  # not an allowed status
        {"name": "X" * 201},
    ],
)
def test_project_validation(
    client: TestClient, tenants: Tenants, acme_board: Board, body: dict[str, str]
) -> None:
    response = client.post(
        _projects(tenants.acme),
        json={"workspace_id": acme_board.workspace_id, **body},
        headers=tenants.member.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("which", ["other_org", "missing"])
def test_workspace_must_belong_to_same_org(
    client: TestClient, tenants: Tenants, globex_board: Board, which: str
) -> None:
    workspace_id = globex_board.workspace_id if which == "other_org" else str(uuid.uuid4())
    response = client.post(
        _projects(tenants.acme),
        json={"workspace_id": workspace_id, "name": "Sneaky"},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"


def test_tenant_comes_from_path_not_body(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    response = client.post(
        _projects(tenants.acme),
        json={
            "workspace_id": acme_board.workspace_id,
            "name": "X",
            "organization_id": str(tenants.globex),
        },
        headers=tenants.owner.headers,
    )
    assert response.status_code == 422
    assert db.scalar(select(Project).where(Project.organization_id == tenants.globex)) is None


# --- read / update / delete -----------------------------------------------------


def test_get_project(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    response = client.get(
        f"/api/v1/projects/{acme_board.project_id}", headers=tenants.viewer.headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Launch"


def test_outsider_and_missing_project_look_identical(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    real = client.get(f"/api/v1/projects/{acme_board.project_id}", headers=tenants.mallory.headers)
    fake = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=tenants.mallory.headers)
    assert real.status_code == fake.status_code == 404
    assert real.json()["error"]["code"] == fake.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_update_project_with_version(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    path = f"/api/v1/projects/{acme_board.project_id}"
    response = client.patch(
        path,
        json={"version": 1, "status": "on_hold", "name": "Launch v2"},
        headers=tenants.member.headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "on_hold"
    assert response.json()["version"] == 2


def test_stale_version_is_rejected(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    path = f"/api/v1/projects/{acme_board.project_id}"
    client.patch(path, json={"version": 1, "name": "First"}, headers=tenants.member.headers)
    # A second editor still holding version 1 must not silently overwrite.
    response = client.patch(
        path, json={"version": 1, "name": "Second"}, headers=tenants.admin.headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"
    assert response.json()["error"]["details"][0]["current_version"] == 2
    assert client.get(path, headers=tenants.member.headers).json()["name"] == "First"


@pytest.mark.parametrize(
    "body",
    [{"name": "No version"}, {"version": 1, "name": None}, {"version": 1, "status": "bogus"}],
)
def test_update_validation(
    client: TestClient, tenants: Tenants, acme_board: Board, body: dict[str, object]
) -> None:
    response = client.patch(
        f"/api/v1/projects/{acme_board.project_id}", json=body, headers=tenants.member.headers
    )
    assert response.status_code == 422


def test_cannot_move_project_to_other_orgs_workspace(
    client: TestClient, tenants: Tenants, acme_board: Board, globex_board: Board
) -> None:
    response = client.patch(
        f"/api/v1/projects/{acme_board.project_id}",
        json={"version": 1, "workspace_id": globex_board.workspace_id},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 422


def test_move_project_between_own_workspaces(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    other = create_workspace(client, tenants.owner, tenants.acme, "other")
    response = client.patch(
        f"/api/v1/projects/{acme_board.project_id}",
        json={"version": 1, "workspace_id": other["id"]},
        headers=tenants.member.headers,
    )
    assert response.status_code == 200
    assert response.json()["workspace_id"] == other["id"]


@pytest.mark.parametrize(("who", "expected"), [("member", 403), ("viewer", 403), ("mallory", 404)])
def test_only_managers_delete_projects(
    client: TestClient, tenants: Tenants, acme_board: Board, who: str, expected: int
) -> None:
    actor = getattr(tenants, who)
    response = client.delete(f"/api/v1/projects/{acme_board.project_id}", headers=actor.headers)
    assert response.status_code == expected


def test_deleting_project_deletes_its_tasks(
    client: TestClient, db: Session, tenants: Tenants, acme_board: Board
) -> None:
    create_task(client, tenants.member, acme_board.project_id, "Doomed")
    response = client.delete(
        f"/api/v1/projects/{acme_board.project_id}", headers=tenants.admin.headers
    )
    assert response.status_code == 204
    db.expire_all()
    assert db.scalar(select(Task).where(Task.project_id == acme_board.project_id)) is None


# --- list: pagination, filters, search, sorting ---------------------------------


@pytest.fixture
def many_projects(client: TestClient, tenants: Tenants, acme_board: Board) -> None:
    for name, status in [
        ("Apollo", "active"),
        ("Gemini", "on_hold"),
        ("Mercury", "completed"),
        ("Artemis 100%", "active"),
    ]:
        create_project(
            client, tenants.member, tenants.acme, acme_board.workspace_id, name, status=status
        )
    globex_ws = create_workspace(client, tenants.mallory, tenants.globex, "lab")
    create_project(client, tenants.mallory, tenants.globex, globex_ws["id"], "Apollo Globex")


def _list(client: TestClient, tenants: Tenants, **params: object) -> dict:  # type: ignore[type-arg]
    response = client.get(_projects(tenants.acme), params=params, headers=tenants.viewer.headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_list_only_returns_own_tenant(
    client: TestClient, tenants: Tenants, many_projects: None
) -> None:
    body = _list(client, tenants, page_size=100)
    assert body["total"] == 5  # Launch + 4 above; Globex's project excluded
    assert all(p["organization_id"] == str(tenants.acme) for p in body["items"])


def test_pagination(client: TestClient, tenants: Tenants, many_projects: None) -> None:
    first = _list(client, tenants, page=1, page_size=2, sort="name")
    second = _list(client, tenants, page=2, page_size=2, sort="name")
    third = _list(client, tenants, page=3, page_size=2, sort="name")
    names = [p["name"] for page in (first, second, third) for p in page["items"]]
    assert names == ["Apollo", "Artemis 100%", "Gemini", "Launch", "Mercury"]
    assert first["total_pages"] == 3


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_pagination_bounds(client: TestClient, tenants: Tenants, params: dict[str, int]) -> None:
    response = client.get(_projects(tenants.acme), params=params, headers=tenants.viewer.headers)
    assert response.status_code == 422


def test_filter_by_status(client: TestClient, tenants: Tenants, many_projects: None) -> None:
    body = _list(client, tenants, status="active", sort="name")
    assert [p["name"] for p in body["items"]] == ["Apollo", "Artemis 100%", "Launch"]


def test_search_is_case_insensitive_and_escapes_wildcards(
    client: TestClient, tenants: Tenants, many_projects: None
) -> None:
    assert [p["name"] for p in _list(client, tenants, q="apo")["items"]] == ["Apollo"]
    # '%' is a literal, not "match anything".
    assert [p["name"] for p in _list(client, tenants, q="100%")["items"]] == ["Artemis 100%"]
    assert _list(client, tenants, q="%")["total"] == 1


def test_sort_allowlist(client: TestClient, tenants: Tenants) -> None:
    response = client.get(
        _projects(tenants.acme), params={"sort": "description"}, headers=tenants.viewer.headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SORT_FIELD"
    injection = client.get(
        _projects(tenants.acme), params={"sort": "name;drop table"}, headers=tenants.viewer.headers
    )
    assert injection.status_code == 422
