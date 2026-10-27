from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.db.models import Invitation, Membership, MembershipRole
from tests.conftest import Tenants
from tests.helpers import accept, create_actor, invite

ORGS = "/api/v1/organizations"


def test_admin_invites_and_user_accepts(client: TestClient, db: Session, tenants: Tenants) -> None:
    created = invite(client, tenants.admin, tenants.acme, "  New.Hire@Example.com ", "viewer")
    assert created.status_code == 201
    body = created.json()
    assert body["email"] == "new.hire@example.com"
    assert body["role"] == "viewer"
    assert body["invited_by_id"] == str(tenants.admin.id)

    new_hire = create_actor(client, "new.hire@example.com")
    accepted = accept(client, new_hire, body["token"])
    assert accepted.status_code == 200
    assert accepted.json()["slug"] == "acme"
    assert accepted.json()["role"] == "viewer"

    membership = db.scalar(select(Membership).where(Membership.user_id == new_hire.id))
    assert membership is not None and membership.role is MembershipRole.VIEWER
    invitation = db.get(Invitation, body["id"])
    assert invitation is not None
    assert invitation.accepted_at is not None
    assert invitation.accepted_by_id == new_hire.id


def test_token_is_stored_only_as_hash(client: TestClient, db: Session, tenants: Tenants) -> None:
    token = invite(client, tenants.owner, tenants.acme, "x@example.com").json()["token"]
    stored = db.scalars(select(Invitation.token_hash)).all()
    assert token not in stored
    assert security.hash_opaque_token(token) in stored


def test_owner_can_invite_admin(client: TestClient, tenants: Tenants) -> None:
    assert invite(client, tenants.owner, tenants.acme, "a@example.com", "admin").status_code == 201


def test_admin_cannot_invite_admin(client: TestClient, tenants: Tenants) -> None:
    assert invite(client, tenants.admin, tenants.acme, "a@example.com", "admin").status_code == 403


def test_owner_role_cannot_be_invited(client: TestClient, tenants: Tenants) -> None:
    assert invite(client, tenants.owner, tenants.acme, "a@example.com", "owner").status_code == 422


def test_inviting_existing_member_conflicts(client: TestClient, tenants: Tenants) -> None:
    response = invite(client, tenants.owner, tenants.acme, tenants.member.email)
    assert response.status_code == 409


def test_reinvite_replaces_previous_link(client: TestClient, tenants: Tenants) -> None:
    first = invite(client, tenants.owner, tenants.acme, "late@example.com").json()["token"]
    second = invite(client, tenants.owner, tenants.acme, "late@example.com").json()["token"]
    late = create_actor(client, "late@example.com")

    assert accept(client, late, first).status_code == 410
    assert accept(client, late, second).status_code == 200


def test_list_pending_invitations(client: TestClient, tenants: Tenants) -> None:
    invite(client, tenants.owner, tenants.acme, "pending@example.com")
    response = client.get(f"{ORGS}/{tenants.acme}/invitations", headers=tenants.admin.headers)
    assert response.status_code == 200
    # Accepted invitations from the fixture are not listed; tokens are never listed.
    assert [i["email"] for i in response.json()] == ["pending@example.com"]
    assert "token" not in response.json()[0]


def test_members_cannot_list_invitations(client: TestClient, tenants: Tenants) -> None:
    response = client.get(f"{ORGS}/{tenants.acme}/invitations", headers=tenants.member.headers)
    assert response.status_code == 403


def test_accept_with_wrong_email_is_rejected(
    client: TestClient, db: Session, tenants: Tenants
) -> None:
    token = invite(client, tenants.owner, tenants.acme, "intended@example.com").json()["token"]
    # Mallory got hold of the link but is signed in as herself.
    response = accept(client, tenants.mallory, token)
    assert response.status_code == 403
    assert (
        db.scalar(
            select(Membership).where(
                Membership.user_id == tenants.mallory.id,
                Membership.organization_id == tenants.acme,
            )
        )
        is None
    )


def test_accept_unknown_token_is_404(client: TestClient, tenants: Tenants) -> None:
    response = accept(client, tenants.mallory, security.generate_opaque_token())
    assert response.status_code == 404


def test_accept_requires_authentication(client: TestClient, tenants: Tenants) -> None:
    token = invite(client, tenants.owner, tenants.acme, "anon@example.com").json()["token"]
    assert client.post("/api/v1/invitations/accept", json={"token": token}).status_code == 401


def test_revoke_pending_invitation(client: TestClient, tenants: Tenants) -> None:
    invitation_id = invite(client, tenants.owner, tenants.acme, "r@example.com").json()["id"]
    path = f"{ORGS}/{tenants.acme}/invitations/{invitation_id}"
    assert client.delete(path, headers=tenants.admin.headers).status_code == 204
    assert client.delete(path, headers=tenants.admin.headers).status_code == 409


def test_admin_cannot_revoke_admin_invitation(client: TestClient, tenants: Tenants) -> None:
    invitation_id = invite(client, tenants.owner, tenants.acme, "r@example.com", "admin").json()[
        "id"
    ]
    path = f"{ORGS}/{tenants.acme}/invitations/{invitation_id}"
    assert client.delete(path, headers=tenants.admin.headers).status_code == 403
