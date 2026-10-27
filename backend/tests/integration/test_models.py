import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    ActivityLog,
    Membership,
    MembershipRole,
    Organization,
    Project,
    Task,
    TaskStatus,
    User,
    Workspace,
)


def _user(db: Session, email: str = "owner@example.com") -> User:
    user = User(email=email, password_hash="x")
    db.add(user)
    db.flush()
    return user


def _org(db: Session, slug: str) -> Organization:
    org = Organization(name=slug.title(), slug=slug)
    db.add(org)
    db.flush()
    return org


def _workspace(db: Session, org: Organization, slug: str = "main") -> Workspace:
    ws = Workspace(organization_id=org.id, name=slug, slug=slug)
    db.add(ws)
    db.flush()
    return ws


def _expect_integrity_error(db: Session, build: Callable[[], object]) -> None:
    # raises() must wrap begin_nested() so the savepoint sees the error and rolls back.
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(build())
        db.flush()


def test_full_hierarchy_and_defaults(db: Session) -> None:
    user = _user(db)
    org = _org(db, "acme")
    db.add(Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER))
    ws = _workspace(db, org)
    project = Project(organization_id=org.id, workspace_id=ws.id, name="Launch")
    db.add(project)
    db.flush()
    task = Task(
        organization_id=org.id, project_id=project.id, title="Ship it", created_by_id=user.id
    )
    db.add(task)
    db.flush()
    db.add(
        ActivityLog(
            organization_id=org.id,
            actor_id=user.id,
            action="task.created",
            entity_type="task",
            entity_id=task.id,
        )
    )
    db.flush()
    db.refresh(task)

    assert task.status is TaskStatus.TODO
    assert task.created_at is not None and task.updated_at is not None


def test_user_email_must_be_unique(db: Session) -> None:
    _user(db, "dup@example.com")
    _expect_integrity_error(db, lambda: User(email="dup@example.com", password_hash="x"))


def test_db_rejects_non_normalized_email(db: Session) -> None:
    _expect_integrity_error(db, lambda: User(email="Mixed@Example.com", password_hash="x"))


def test_membership_is_unique_per_org_and_user(db: Session) -> None:
    user, org = _user(db), _org(db, "acme")
    db.add(Membership(organization_id=org.id, user_id=user.id))
    db.flush()
    _expect_integrity_error(db, lambda: Membership(organization_id=org.id, user_id=user.id))


def test_workspace_slug_unique_within_org_only(db: Session) -> None:
    acme, globex = _org(db, "acme"), _org(db, "globex")
    _workspace(db, acme, "eng")
    _workspace(db, globex, "eng")  # same slug, different tenant: allowed
    _expect_integrity_error(db, lambda: Workspace(organization_id=acme.id, name="x", slug="eng"))


def test_project_cannot_reference_another_tenants_workspace(db: Session) -> None:
    acme, globex = _org(db, "acme"), _org(db, "globex")
    globex_ws = _workspace(db, globex)
    _expect_integrity_error(
        db, lambda: Project(organization_id=acme.id, workspace_id=globex_ws.id, name="Sneaky")
    )


def test_task_cannot_reference_another_tenants_project(db: Session) -> None:
    acme, globex = _org(db, "acme"), _org(db, "globex")
    ws = _workspace(db, globex)
    project = Project(organization_id=globex.id, workspace_id=ws.id, name="Theirs")
    db.add(project)
    db.flush()
    _expect_integrity_error(
        db, lambda: Task(organization_id=acme.id, project_id=project.id, title="Sneaky")
    )


def test_invalid_enum_value_rejected_by_db(db: Session) -> None:
    user, org = _user(db), _org(db, "acme")
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            Membership.__table__.insert().values(
                id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="superuser"
            )
        )


def test_deleting_org_cascades_to_tenant_data(db: Session) -> None:
    user, org = _user(db), _org(db, "acme")
    db.add(Membership(organization_id=org.id, user_id=user.id))
    ws = _workspace(db, org)
    project = Project(organization_id=org.id, workspace_id=ws.id, name="P")
    db.add(project)
    db.flush()
    db.add(Task(organization_id=org.id, project_id=project.id, title="T"))
    db.flush()

    db.delete(org)
    db.flush()
    db.expunge_all()

    assert db.scalar(select(Task)) is None
    assert db.scalar(select(Project)) is None
    assert db.scalar(select(Workspace)) is None
    assert db.scalar(select(Membership)) is None
    assert db.get(User, user.id) is not None  # users outlive organizations
