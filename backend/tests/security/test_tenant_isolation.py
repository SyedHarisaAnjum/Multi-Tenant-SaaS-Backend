"""Phase 6: authorization and tenant-isolation attacks.

Project and task APIs arrive later, so cross-tenant resource access is exercised through
a small probe app whose routes use the real `AccessibleProject` / `AccessibleTask` /
`OrgContributor` dependencies, the same building blocks the real routes will use.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi import APIRouter, Body, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import register_exception_handlers
from app.db.models import (
    Invitation,
    Membership,
    MembershipRole,
    Project,
    Task,
    Workspace,
)
from app.db.session import get_db
from app.dependencies.auth import DbSession
from app.dependencies.organizations import OrgContributor
from app.dependencies.resources import AccessibleProject, AccessibleTask
from tests.conftest import Tenants
from tests.helpers import accept, create_actor, invite

ORGS = "/api/v1/organizations"

# --- probe app ------------------------------------------------------------------

_probe = APIRouter(prefix="/probe/organizations/{organization_id}")


@_probe.get("/projects/{project_id}")
def _read_project(project: AccessibleProject) -> dict[str, Any]:
    return {"id": str(project.id), "name": project.name}


@_probe.patch("/tasks/{task_id}")
def _rename_task(
    task: AccessibleTask, _: OrgContributor, db: DbSession, title: str = Body(embed=True)
) -> dict[str, Any]:
    task.title = title
    db.commit()
    return {"id": str(task.id), "title": task.title}


@pytest.fixture
def probe(db: Session) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(_probe)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def _seed_project_and_task(db: Session, organization_id: uuid.UUID) -> tuple[Project, Task]:
    workspace = Workspace(organization_id=organization_id, name="Main", slug="main")
    db.add(workspace)
    db.flush()
    project = Project(organization_id=organization_id, workspace_id=workspace.id, name="Secret")
    db.add(project)
    db.flush()
    task = Task(organization_id=organization_id, project_id=project.id, title="Original")
    db.add(task)
    db.flush()
    return project, task


def _membership(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    db.expire_all()
    return db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user_id
        )
    )


# --- 1. accessing an organization you don't belong to --------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PATCH", "", {"name": "Pwned"}),
        ("GET", "/members", None),
        ("GET", "/invitations", None),
        ("POST", "/invitations", {"email": "x@example.com"}),
        ("POST", "/transfer-ownership", {"user_id": str(uuid.uuid4())}),
    ],
)
def test_outsider_cannot_access_organization(
    client: TestClient, tenants: Tenants, method: str, suffix: str, body: dict[str, Any] | None
) -> None:
    response = client.request(
        method, f"{ORGS}/{tenants.acme}{suffix}", json=body, headers=tenants.mallory.headers
    )
    # 404 (not 403): outsiders can't even confirm the organization exists.
    assert response.status_code == 404


def test_outsider_and_nonexistent_org_are_indistinguishable(
    client: TestClient, tenants: Tenants
) -> None:
    real = client.get(f"{ORGS}/{tenants.acme}", headers=tenants.mallory.headers)
    fake = client.get(f"{ORGS}/{uuid.uuid4()}", headers=tenants.mallory.headers)
    assert real.status_code == fake.status_code == 404
    assert real.json()["error"]["code"] == fake.json()["error"]["code"]
    assert real.json()["error"]["message"] == fake.json()["error"]["message"]


def test_outsider_cannot_remove_members(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.delete(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}", headers=tenants.mallory.headers
    )
    assert response.status_code == 404
    assert _membership(db, tenants.acme, tenants.member.id) is not None


# --- 2. accessing another organization's project ------------------------------


def test_cannot_read_other_orgs_project_via_own_org(
    probe: TestClient, db: Session, tenants: Tenants
) -> None:
    acme_project, _ = _seed_project_and_task(db, tenants.acme)
    # Mallory is a legitimate member of Globex and knows Acme's project UUID.
    response = probe.get(
        f"/probe/organizations/{tenants.globex}/projects/{acme_project.id}",
        headers=tenants.mallory.headers,
    )
    assert response.status_code == 404


def test_cannot_read_other_orgs_project_via_their_org(
    probe: TestClient, db: Session, tenants: Tenants
) -> None:
    acme_project, _ = _seed_project_and_task(db, tenants.acme)
    response = probe.get(
        f"/probe/organizations/{tenants.acme}/projects/{acme_project.id}",
        headers=tenants.mallory.headers,
    )
    assert response.status_code == 404


def test_member_can_read_own_orgs_project(probe: TestClient, db: Session, tenants: Tenants) -> None:
    acme_project, _ = _seed_project_and_task(db, tenants.acme)
    response = probe.get(
        f"/probe/organizations/{tenants.acme}/projects/{acme_project.id}",
        headers=tenants.viewer.headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Secret"


# --- 3. modifying another organization's task ---------------------------------


@pytest.mark.parametrize("via_org", ["globex", "acme"])
def test_cannot_modify_other_orgs_task(
    probe: TestClient, db: Session, tenants: Tenants, via_org: str
) -> None:
    _, acme_task = _seed_project_and_task(db, tenants.acme)
    org_id = getattr(tenants, via_org)
    response = probe.patch(
        f"/probe/organizations/{org_id}/tasks/{acme_task.id}",
        json={"title": "Pwned"},
        headers=tenants.mallory.headers,
    )
    assert response.status_code == 404
    db.expire_all()
    assert db.get(Task, acme_task.id).title == "Original"  # type: ignore[union-attr]


def test_viewer_cannot_modify_own_orgs_task(
    probe: TestClient, db: Session, tenants: Tenants
) -> None:
    _, task = _seed_project_and_task(db, tenants.acme)
    response = probe.patch(
        f"/probe/organizations/{tenants.acme}/tasks/{task.id}",
        json={"title": "Edited"},
        headers=tenants.viewer.headers,
    )
    assert response.status_code == 403


def test_member_can_modify_own_orgs_task(probe: TestClient, db: Session, tenants: Tenants) -> None:
    _, task = _seed_project_and_task(db, tenants.acme)
    response = probe.patch(
        f"/probe/organizations/{tenants.acme}/tasks/{task.id}",
        json={"title": "Edited"},
        headers=tenants.member.headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Edited"


# --- 4. member attempting to promote themselves --------------------------------


@pytest.mark.parametrize(("who", "target_role"), [("member", "admin"), ("viewer", "member")])
def test_member_cannot_promote_themselves(
    client: TestClient, db: Session, tenants: Tenants, who: str, target_role: str
) -> None:
    actor = getattr(tenants, who)
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{actor.id}",
        json={"role": target_role},
        headers=actor.headers,
    )
    assert response.status_code == 403
    membership = _membership(db, tenants.acme, actor.id)
    assert membership is not None and membership.role.value == who


def test_admin_cannot_change_own_role(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.admin.id}",
        json={"role": "viewer"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 403


def test_member_cannot_promote_a_colleague(client: TestClient, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.viewer.id}",
        json={"role": "admin"},
        headers=tenants.member.headers,
    )
    assert response.status_code == 403


def test_member_cannot_self_promote_via_invitation(client: TestClient, tenants: Tenants) -> None:
    # A second account under the attacker's control, invited with elevated rights.
    assert (
        invite(client, tenants.member, tenants.acme, "sock@example.com", "admin").status_code == 403
    )


# --- 5. admin attempting to transfer ownership --------------------------------


def test_admin_cannot_transfer_ownership(client: TestClient, db: Session, tenants: Tenants) -> None:
    for target in (tenants.admin, tenants.member):
        response = client.post(
            f"{ORGS}/{tenants.acme}/transfer-ownership",
            json={"user_id": str(target.id)},
            headers=tenants.admin.headers,
        )
        assert response.status_code == 403
    owner = _membership(db, tenants.acme, tenants.owner.id)
    assert owner is not None and owner.role is MembershipRole.OWNER


def test_admin_cannot_take_ownership_via_role_change(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.admin.id}",
        json={"role": "owner"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 422
    admin = _membership(db, tenants.acme, tenants.admin.id)
    assert admin is not None and admin.role is MembershipRole.ADMIN


def test_database_enforces_a_single_owner(db: Session, tenants: Tenants) -> None:
    admin = _membership(db, tenants.acme, tenants.admin.id)
    assert admin is not None
    with pytest.raises(IntegrityError), db.begin_nested():
        admin.role = MembershipRole.OWNER
        db.flush()


# --- 6. unauthorized user inviting a member ------------------------------------


@pytest.mark.parametrize(("who", "expected"), [("member", 403), ("viewer", 403), ("mallory", 404)])
def test_unauthorized_user_cannot_invite(
    client: TestClient, db: Session, tenants: Tenants, who: str, expected: int
) -> None:
    actor = getattr(tenants, who)
    response = invite(client, actor, tenants.acme, "friend@example.com", "member")
    assert response.status_code == expected
    assert db.scalar(select(Invitation).where(Invitation.email == "friend@example.com")) is None


def test_unauthenticated_user_cannot_invite(client: TestClient, tenants: Tenants) -> None:
    response = client.post(
        f"{ORGS}/{tenants.acme}/invitations", json={"email": "friend@example.com"}
    )
    assert response.status_code == 401


# --- 7. expired invitation being accepted --------------------------------------


def test_expired_invitation_cannot_be_accepted(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    created = invite(client, tenants.owner, tenants.acme, "slow@example.com").json()
    invitation = db.get(Invitation, uuid.UUID(created["id"]))
    assert invitation is not None
    invitation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    slow = create_actor(client, "slow@example.com")
    response = accept(client, slow, created["token"])
    assert response.status_code == 410
    assert "expired" in response.json()["error"]["message"]
    assert _membership(db, tenants.acme, slow.id) is None


# --- 8. revoked invitation being reused ----------------------------------------


def test_revoked_invitation_cannot_be_used(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    created = invite(client, tenants.owner, tenants.acme, "revoked@example.com").json()
    revoke = client.delete(
        f"{ORGS}/{tenants.acme}/invitations/{created['id']}", headers=tenants.admin.headers
    )
    assert revoke.status_code == 204

    invitee = create_actor(client, "revoked@example.com")
    response = accept(client, invitee, created["token"])
    assert response.status_code == 410
    assert "revoked" in response.json()["error"]["message"]
    assert _membership(db, tenants.acme, invitee.id) is None


def test_accepted_invitation_cannot_be_reused_after_removal(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    created = invite(client, tenants.owner, tenants.acme, "once@example.com").json()
    user = create_actor(client, "once@example.com")
    assert accept(client, user, created["token"]).status_code == 200

    # Removed, then tries to rejoin by replaying the same link.
    client.delete(f"{ORGS}/{tenants.acme}/members/{user.id}", headers=tenants.owner.headers)
    response = accept(client, user, created["token"])
    assert response.status_code == 410
    assert "already been used" in response.json()["error"]["message"]
    assert _membership(db, tenants.acme, user.id) is None


def test_invitation_token_does_not_work_after_tampering(
    client: TestClient, tenants: Tenants
) -> None:
    token = invite(client, tenants.owner, tenants.acme, "t@example.com").json()["token"]
    user = create_actor(client, "t@example.com")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert accept(client, user, tampered).status_code == 404


# --- 9. removed member reusing an existing access token ------------------------


def test_removed_member_loses_access_with_still_valid_token(
    client: TestClient, probe: TestClient, db: Session, tenants: Tenants
) -> None:
    project, task = _seed_project_and_task(db, tenants.acme)
    member = tenants.member
    org = f"{ORGS}/{tenants.acme}"

    # Before removal: the token grants access.
    assert client.get(org, headers=member.headers).status_code == 200
    project_url = f"/probe/organizations/{tenants.acme}/projects/{project.id}"
    assert probe.get(project_url, headers=member.headers).status_code == 200

    assert (
        client.delete(f"{org}/members/{member.id}", headers=tenants.owner.headers).status_code
        == 204
    )

    # The access token itself is still valid (signature and expiry)...
    assert client.get("/api/v1/auth/me", headers=member.headers).status_code == 200
    # ...but grants nothing in the organization any more.
    assert client.get(org, headers=member.headers).status_code == 404
    assert client.get(f"{org}/members", headers=member.headers).status_code == 404
    assert probe.get(project_url, headers=member.headers).status_code == 404
    rename = probe.patch(
        f"/probe/organizations/{tenants.acme}/tasks/{task.id}",
        json={"title": "Revenge"},
        headers=member.headers,
    )
    assert rename.status_code == 404
    assert client.get(ORGS, headers=member.headers).json() == []


def test_removed_admin_cannot_invite_with_old_token(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    client.delete(
        f"{ORGS}/{tenants.acme}/members/{tenants.admin.id}", headers=tenants.owner.headers
    )
    response = invite(client, tenants.admin, tenants.acme, "backdoor@example.com", "member")
    assert response.status_code == 404
    assert db.scalar(select(Invitation).where(Invitation.email == "backdoor@example.com")) is None


def test_demoted_admin_loses_admin_rights_immediately(client: TestClient, tenants: Tenants) -> None:
    org = f"{ORGS}/{tenants.acme}"
    demote = client.patch(
        f"{org}/members/{tenants.admin.id}", json={"role": "viewer"}, headers=tenants.owner.headers
    )
    assert demote.status_code == 200
    assert client.patch(org, json={"name": "x"}, headers=tenants.admin.headers).status_code == 403
    assert invite(client, tenants.admin, tenants.acme, "y@example.com").status_code == 403
