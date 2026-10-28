import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Workspace
from tests.conftest import Board, Tenants
from tests.helpers import create_project, create_workspace


def _ws(org: object) -> str:
    return f"/api/v1/organizations/{org}/workspaces"


def test_admin_creates_workspace(client: TestClient, tenants: Tenants) -> None:
    response = client.post(
        _ws(tenants.acme),
        json={"name": " Design ", "slug": "design"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Design"
    assert body["organization_id"] == str(tenants.acme)


@pytest.mark.parametrize("who", ["member", "viewer"])
def test_non_managers_cannot_create_workspace(
    client: TestClient, tenants: Tenants, who: str
) -> None:
    actor = getattr(tenants, who)
    response = client.post(
        _ws(tenants.acme), json={"name": "X", "slug": "xyz"}, headers=actor.headers
    )
    assert response.status_code == 403


def test_slug_unique_within_org_only(client: TestClient, tenants: Tenants) -> None:
    create_workspace(client, tenants.owner, tenants.acme, "shared")
    duplicate = client.post(
        _ws(tenants.acme), json={"name": "Again", "slug": "shared"}, headers=tenants.owner.headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "WORKSPACE_SLUG_TAKEN"
    create_workspace(client, tenants.mallory, tenants.globex, "shared")  # other tenant: fine


def test_cannot_smuggle_organization_id_in_body(client: TestClient, tenants: Tenants) -> None:
    response = client.post(
        _ws(tenants.acme),
        json={"name": "X", "slug": "xyz", "organization_id": str(tenants.globex)},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.organization_id"


def test_list_workspaces_paginated_sorted_and_searchable(
    client: TestClient, tenants: Tenants
) -> None:
    for slug in ("alpha", "bravo", "charlie", "delta"):
        create_workspace(client, tenants.owner, tenants.acme, slug)
    create_workspace(client, tenants.mallory, tenants.globex, "alpha-globex")

    page = client.get(
        _ws(tenants.acme), params={"page": 2, "page_size": 3}, headers=tenants.viewer.headers
    ).json()
    assert page["total"] == 4  # tenant filter applied before pagination
    assert page["total_pages"] == 2
    assert [w["slug"] for w in page["items"]] == ["delta"]

    desc = client.get(_ws(tenants.acme), params={"sort": "-name"}, headers=tenants.viewer.headers)
    assert [w["slug"] for w in desc.json()["items"]][:2] == ["delta", "charlie"]

    found = client.get(_ws(tenants.acme), params={"q": "RAV"}, headers=tenants.viewer.headers)
    assert [w["slug"] for w in found.json()["items"]] == ["bravo"]


def test_update_workspace(client: TestClient, tenants: Tenants) -> None:
    ws = create_workspace(client, tenants.owner, tenants.acme, "old")
    response = client.patch(
        f"{_ws(tenants.acme)}/{ws['id']}",
        json={"name": "Renamed", "slug": "new"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["slug"]) == ("Renamed", "new")


def test_member_cannot_update_workspace(client: TestClient, tenants: Tenants) -> None:
    ws = create_workspace(client, tenants.owner, tenants.acme, "old")
    response = client.patch(
        f"{_ws(tenants.acme)}/{ws['id']}", json={"name": "Nope"}, headers=tenants.member.headers
    )
    assert response.status_code == 403


def test_delete_empty_workspace(client: TestClient, tenants: Tenants) -> None:
    ws = create_workspace(client, tenants.owner, tenants.acme, "temp")
    path = f"{_ws(tenants.acme)}/{ws['id']}"
    assert client.delete(path, headers=tenants.admin.headers).status_code == 204
    assert client.get(path, headers=tenants.admin.headers).status_code == 404


def test_delete_rejected_while_workspace_has_projects(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    path = f"{_ws(tenants.acme)}/{acme_board.workspace_id}"
    response = client.delete(path, headers=tenants.owner.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_EMPTY"

    client.delete(f"/api/v1/projects/{acme_board.project_id}", headers=tenants.owner.headers)
    assert client.delete(path, headers=tenants.owner.headers).status_code == 204


def test_database_restricts_deleting_non_empty_workspace(
    db: Session, tenants: Tenants, acme_board: Board
) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(delete(Workspace).where(Workspace.id == acme_board.workspace_id))


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_cannot_access_other_orgs_workspace(
    client: TestClient, tenants: Tenants, globex_board: Board, method: str
) -> None:
    body = {"name": "Pwned"} if method == "PATCH" else None
    for org in (tenants.acme, tenants.globex):  # via own org, and via theirs
        response = client.request(
            method,
            f"{_ws(org)}/{globex_board.workspace_id}",
            json=body,
            headers=tenants.owner.headers,
        )
        assert response.status_code == 404


def test_project_name_unique_per_workspace(
    client: TestClient, tenants: Tenants, acme_board: Board
) -> None:
    response = client.post(
        f"/api/v1/organizations/{tenants.acme}/projects",
        json={"workspace_id": acme_board.workspace_id, "name": "Launch"},
        headers=tenants.member.headers,
    )
    assert response.status_code == 409
    other = create_workspace(client, tenants.owner, tenants.acme, "other")
    create_project(client, tenants.member, tenants.acme, other["id"], "Launch")
