"""Phase 12: transactions and concurrency, exercised with real concurrent requests.

Unlike the rest of the suite (one rolled-back transaction per test), these tests run
requests on separate threads with their own database connections and real commits,
then truncate everything. A threading.Barrier holds both requests at the exact point
where application-level checks have passed, so only database constraints and row
locks can stop the second one.
"""

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm.exc import StaleDataError

from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.core.redis import get_redis
from app.db.models import Membership, MembershipRole, Organization, Task
from app.db.session import SessionLocal, engine
from app.main import app
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.task_repository import TaskRepository
from app.services import task_service
from tests.helpers import (
    Actor,
    add_member,
    create_actor,
    create_org,
    create_project,
    create_task,
    create_workspace,
    invite,
)


@pytest.fixture
def live() -> Iterator[TestClient]:
    """The real app with real sessions (no shared test transaction)."""
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(get_redis(), enabled=False)
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE users, organizations CASCADE"))


def concurrently(*calls: Callable[[], Any]) -> list[Any]:
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [f.result(timeout=30) for f in [pool.submit(c) for c in calls]]


def pause_after(cls: Any, name: str, barrier: threading.Barrier, mp: pytest.MonkeyPatch) -> None:
    """Make both threads finish `cls.name` before either continues."""
    original = getattr(cls, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        barrier.wait()
        return result

    mp.setattr(cls, name, wrapper)


def pause_before(cls: Any, name: str, barrier: threading.Barrier, mp: pytest.MonkeyPatch) -> None:
    original = getattr(cls, name)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        barrier.wait()
        return original(*args, **kwargs)

    mp.setattr(cls, name, wrapper)


def _count(stmt: Any) -> int:
    with SessionLocal() as session:
        return session.scalar(stmt) or 0


# --- unique resources -----------------------------------------------------------


def test_two_requests_claiming_same_slug(live: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    alice = create_actor(live, "alice@example.com")
    bob = create_actor(live, "bob@example.com")
    # Both requests see "slug is free" before either inserts.
    pause_after(
        OrganizationRepository, "get_by_slug", threading.Barrier(2, timeout=10), monkeypatch
    )

    def claim(actor: Actor) -> Callable[[], Any]:
        return lambda: TestClient(app).post(
            "/api/v1/organizations", json={"name": "Race", "slug": "race"}, headers=actor.headers
        )

    responses = concurrently(claim(alice), claim(bob))
    assert sorted(r.status_code for r in responses) == [201, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["error"]["code"] == "SLUG_TAKEN"  # unique index, translated cleanly
    assert _count(select(func.count()).select_from(Organization)) == 1
    # And the loser's half-done work (its owner membership) was rolled back with it.
    assert _count(select(func.count()).select_from(Membership)) == 1


def test_same_invitation_accepted_twice_at_once(
    live: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = create_actor(live, "owner@example.com")
    bob = create_actor(live, "bob@example.com")
    org = create_org(live, owner, "acme")
    token = invite(live, owner, org, bob.email).json()["token"]

    # Both reach the locking SELECT together; FOR UPDATE makes the second wait for
    # the first to commit, after which it sees the invitation already used.
    pause_before(
        InvitationRepository,
        "get_by_hash_for_update",
        threading.Barrier(2, timeout=10),
        monkeypatch,
    )
    accept = lambda: TestClient(app).post(  # noqa: E731
        "/api/v1/invitations/accept", json={"token": token}, headers=bob.headers
    )
    responses = concurrently(accept, accept)

    assert sorted(r.status_code for r in responses) == [200, 410]
    assert (
        _count(select(func.count()).select_from(Membership).where(Membership.user_id == bob.id))
        == 1
    )


# --- optimistic concurrency (lost updates) --------------------------------------


@pytest.fixture
def task(live: TestClient) -> tuple[Actor, Actor, dict[str, Any]]:
    owner = create_actor(live, "owner@example.com")
    member = create_actor(live, "member@example.com")
    org = create_org(live, owner, "acme")
    add_member(live, owner, org, member, "member")
    workspace = create_workspace(live, owner, org, "eng")
    project = create_project(live, owner, org, workspace["id"], "P")
    return owner, member, create_task(live, owner, project["id"], "Original")


def test_concurrent_edits_cannot_overwrite_each_other(
    live: TestClient,
    task: tuple[Actor, Actor, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, member, original = task
    # Both pass the application's version check with version 1...
    pause_after(task_service, "ensure_version", threading.Barrier(2, timeout=10), monkeypatch)

    def edit(actor: Actor, title: str) -> Callable[[], Any]:
        return lambda: TestClient(app).patch(
            f"/api/v1/tasks/{original['id']}",
            json={"version": original["version"], "title": title},
            headers=actor.headers,
        )

    responses = concurrently(edit(owner, "Owner's"), edit(member, "Member's"))
    # ...but UPDATE ... WHERE version = 1 matches only once: the second gets 409.
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()
    loser = next(r for r in responses if r.status_code == 409).json()
    assert loser["error"]["code"] == "VERSION_CONFLICT"

    with SessionLocal() as session:
        stored = session.get(Task, original["id"])
        assert stored is not None
        assert (stored.title, stored.version) == (winner["title"], 2)


def test_orm_version_column_detects_stale_write(task: tuple[Actor, Actor, dict[str, Any]]) -> None:
    _, _, original = task
    with SessionLocal() as first, SessionLocal() as second:
        a = first.get(Task, original["id"])
        b = second.get(Task, original["id"])
        assert a is not None and b is not None
        a.title = "first"
        first.commit()
        b.title = "second"
        with pytest.raises(StaleDataError):
            second.commit()


# --- related records stay consistent --------------------------------------------


def test_assignment_racing_member_removal_never_leaves_orphan_assignee(
    live: TestClient,
    task: tuple[Actor, Actor, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, member, original = task
    barrier = threading.Barrier(2, timeout=10)
    # Assigner validates membership (taking FOR SHARE) and pauses; remover then tries
    # to lock the same membership FOR UPDATE and must wait for the assigner to commit.
    pause_after(TaskRepository, "get_active_member_for_share", barrier, monkeypatch)
    pause_before(MembershipRepository, "get_for_update", barrier, monkeypatch)
    org_id = _org_of(original)

    assign = lambda: TestClient(app).patch(  # noqa: E731
        f"/api/v1/tasks/{original['id']}",
        json={"version": original["version"], "assignee_id": str(member.id)},
        headers=owner.headers,
    )
    remove = lambda: TestClient(app).delete(  # noqa: E731
        f"/api/v1/organizations/{org_id}/members/{member.id}", headers=owner.headers
    )
    assigned, removed = concurrently(assign, remove)
    assert (assigned.status_code, removed.status_code) == (200, 204)

    with SessionLocal() as session:
        stored = session.get(Task, original["id"])
        assert stored is not None
        # The removal's unassign step saw the committed assignment and cleared it.
        assert stored.assignee_id is None


def test_failed_ownership_transfer_leaves_roles_unchanged(
    live: TestClient,
    task: tuple[Actor, Actor, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, member, original = task
    org_id = _org_of(original)

    def fail(*_: Any, **__: Any) -> None:
        raise RuntimeError("crash after the old owner was demoted")

    # The audit write happens after both role changes were flushed.
    monkeypatch.setattr(ActivityLogRepository, "record", fail)
    response = live.post(
        f"/api/v1/organizations/{org_id}/transfer-ownership",
        json={"user_id": str(member.id)},
        headers=owner.headers,
    )
    assert response.status_code == 500

    with SessionLocal() as session:
        roles = dict(
            session.execute(
                select(Membership.user_id, Membership.role).where(
                    Membership.organization_id == org_id
                )
            ).all()
        )
    assert roles == {owner.id: MembershipRole.OWNER, member.id: MembershipRole.MEMBER}


def _org_of(task: dict[str, Any]) -> Any:
    return task["organization_id"]


@pytest.fixture(autouse=True)
def _no_shared_session(request: pytest.FixtureRequest) -> None:
    # Guard: these tests must not use the rolled-back `db`/`client` fixtures.
    assert "db" not in request.fixturenames and "client" not in request.fixturenames
