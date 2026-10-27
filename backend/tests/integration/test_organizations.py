import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActivityLog, Membership, MembershipRole, Organization
from app.repositories.membership_repository import MembershipRepository
from tests.conftest import Tenants
from tests.helpers import add_member, create_actor, create_org

ORGS = "/api/v1/organizations"


def _role(db: Session, tenants: Tenants, user_id: object) -> MembershipRole | None:
    db.expire_all()
    return db.scalar(
        select(Membership.role).where(
            Membership.organization_id == tenants.acme, Membership.user_id == user_id
        )
    )


# --- organizations --------------------------------------------------------------


def test_create_organization_makes_creator_owner(client: TestClient, db: Session) -> None:
    alice = create_actor(client, "alice@example.com")
    response = client.post(
        ORGS, json={"name": "  Acme Inc  ", "slug": "acme-inc"}, headers=alice.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Inc"
    assert body["slug"] == "acme-inc"
    assert body["role"] == "owner"

    membership = db.scalar(select(Membership).where(Membership.user_id == alice.id))
    assert membership is not None
    assert membership.role is MembershipRole.OWNER
    assert str(membership.organization_id) == body["id"]
    assert db.scalar(select(ActivityLog.action)) == "organization.created"


def test_create_organization_rolls_back_if_membership_insert_fails(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = create_actor(client, "alice@example.com")

    def fail(*_: object) -> None:
        raise RuntimeError("simulated failure inserting membership")

    monkeypatch.setattr(MembershipRepository, "add", fail)
    with pytest.raises(RuntimeError):
        client.post(ORGS, json={"name": "Acme", "slug": "acme"}, headers=alice.headers)

    assert db.scalar(select(Organization).where(Organization.slug == "acme")) is None


def test_duplicate_slug_is_rejected(client: TestClient) -> None:
    alice = create_actor(client, "alice@example.com")
    create_org(client, alice, "acme")
    response = client.post(ORGS, json={"name": "Other", "slug": "acme"}, headers=alice.headers)
    assert response.status_code == 409


@pytest.mark.parametrize("slug", ["Acme", "ac", "acme--inc", "-acme", "acme_inc", "acme inc"])
def test_invalid_slug_is_rejected(client: TestClient, slug: str) -> None:
    alice = create_actor(client, "alice@example.com")
    response = client.post(ORGS, json={"name": "Acme", "slug": slug}, headers=alice.headers)
    assert response.status_code == 422


def test_organizations_require_authentication(client: TestClient) -> None:
    assert client.get(ORGS).status_code == 401
    assert client.post(ORGS, json={"name": "A", "slug": "acme"}).status_code == 401


def test_list_returns_only_my_organizations_with_my_role(
    client: TestClient, tenants: Tenants
) -> None:
    response = client.get(ORGS, headers=tenants.member.headers)
    assert response.status_code == 200
    assert [(o["slug"], o["role"]) for o in response.json()] == [("acme", "member")]

    mallory_orgs = client.get(ORGS, headers=tenants.mallory.headers).json()
    assert [o["slug"] for o in mallory_orgs] == ["globex"]


def test_get_organization_as_member(client: TestClient, tenants: Tenants) -> None:
    response = client.get(f"{ORGS}/{tenants.acme}", headers=tenants.viewer.headers)
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_owner_and_admin_can_update_settings(
    client: TestClient, tenants: Tenants, who: str
) -> None:
    actor = getattr(tenants, who)
    response = client.patch(
        f"{ORGS}/{tenants.acme}", json={"name": "Acme Corp"}, headers=actor.headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Acme Corp"


@pytest.mark.parametrize("who", ["member", "viewer"])
def test_member_and_viewer_cannot_update_settings(
    client: TestClient, tenants: Tenants, who: str
) -> None:
    actor = getattr(tenants, who)
    response = client.patch(
        f"{ORGS}/{tenants.acme}", json={"name": "Hacked"}, headers=actor.headers
    )
    assert response.status_code == 403


def test_update_slug_conflict(client: TestClient, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}", json={"slug": "globex"}, headers=tenants.owner.headers
    )
    assert response.status_code == 409


# --- members --------------------------------------------------------------------


def test_list_members(client: TestClient, tenants: Tenants) -> None:
    response = client.get(f"{ORGS}/{tenants.acme}/members", headers=tenants.viewer.headers)
    assert response.status_code == 200
    roles = {m["email"]: m["role"] for m in response.json()}
    assert roles == {
        "owner@acme.com": "owner",
        "admin@acme.com": "admin",
        "member@acme.com": "member",
        "viewer@acme.com": "viewer",
    }


def test_owner_can_promote_member_to_admin(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}",
        json={"role": "admin"},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert _role(db, tenants, tenants.member.id) is MembershipRole.ADMIN


def test_admin_can_change_member_to_viewer(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}",
        json={"role": "viewer"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 200
    assert _role(db, tenants, tenants.member.id) is MembershipRole.VIEWER


def test_admin_cannot_grant_admin(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}",
        json={"role": "admin"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 403
    assert _role(db, tenants, tenants.member.id) is MembershipRole.MEMBER


def test_admin_cannot_demote_owner(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.owner.id}",
        json={"role": "viewer"},
        headers=tenants.admin.headers,
    )
    assert response.status_code == 403
    assert _role(db, tenants, tenants.owner.id) is MembershipRole.OWNER


def test_role_change_for_non_member_is_404(client: TestClient, tenants: Tenants) -> None:
    response = client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.mallory.id}",
        json={"role": "viewer"},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 404


def test_admin_can_remove_member(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.delete(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}", headers=tenants.admin.headers
    )
    assert response.status_code == 204
    assert _role(db, tenants, tenants.member.id) is None


def test_admin_cannot_remove_another_admin(client: TestClient, tenants: Tenants) -> None:
    other_admin = create_actor(client, "admin2@acme.com")
    add_member(client, tenants.owner, tenants.acme, other_admin, "admin")
    response = client.delete(
        f"{ORGS}/{tenants.acme}/members/{other_admin.id}", headers=tenants.admin.headers
    )
    assert response.status_code == 403


def test_member_cannot_remove_others(client: TestClient, tenants: Tenants) -> None:
    response = client.delete(
        f"{ORGS}/{tenants.acme}/members/{tenants.viewer.id}", headers=tenants.member.headers
    )
    assert response.status_code == 403


def test_member_can_leave(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.delete(
        f"{ORGS}/{tenants.acme}/members/{tenants.viewer.id}", headers=tenants.viewer.headers
    )
    assert response.status_code == 204
    assert _role(db, tenants, tenants.viewer.id) is None


def test_owner_cannot_leave_or_be_removed(client: TestClient, tenants: Tenants) -> None:
    path = f"{ORGS}/{tenants.acme}/members/{tenants.owner.id}"
    assert client.delete(path, headers=tenants.owner.headers).status_code == 403
    assert client.delete(path, headers=tenants.admin.headers).status_code == 403


def test_owner_can_transfer_ownership(client: TestClient, db: Session, tenants: Tenants) -> None:
    response = client.post(
        f"{ORGS}/{tenants.acme}/transfer-ownership",
        json={"user_id": str(tenants.member.id)},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 204
    assert _role(db, tenants, tenants.member.id) is MembershipRole.OWNER
    assert _role(db, tenants, tenants.owner.id) is MembershipRole.ADMIN

    # The old owner's still-valid token now carries admin rights only.
    again = client.post(
        f"{ORGS}/{tenants.acme}/transfer-ownership",
        json={"user_id": str(tenants.owner.id)},
        headers=tenants.owner.headers,
    )
    assert again.status_code == 403


def test_transfer_to_non_member_is_404(client: TestClient, tenants: Tenants) -> None:
    response = client.post(
        f"{ORGS}/{tenants.acme}/transfer-ownership",
        json={"user_id": str(tenants.mallory.id)},
        headers=tenants.owner.headers,
    )
    assert response.status_code == 404


def test_role_changes_are_audited(client: TestClient, db: Session, tenants: Tenants) -> None:
    client.patch(
        f"{ORGS}/{tenants.acme}/members/{tenants.member.id}",
        json={"role": "viewer"},
        headers=tenants.owner.headers,
    )
    log = db.scalar(select(ActivityLog).where(ActivityLog.action == "member.role_changed"))
    assert log is not None
    assert log.actor_id == tenants.owner.id
    assert log.details == {"user_id": str(tenants.member.id), "from": "member", "to": "viewer"}
