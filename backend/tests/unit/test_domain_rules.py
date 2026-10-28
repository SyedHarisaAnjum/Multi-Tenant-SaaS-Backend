"""Task status, invitation expiry and update rules as pure functions. No database."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.exceptions import (
    ConflictError,
    GoneError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.db.models import Invitation, MembershipRole, TaskStatus
from app.schemas.projects import ProjectUpdate
from app.schemas.tasks import TaskUpdate
from app.services.invitation_service import ensure_invitation_usable
from app.services.project_service import ensure_version
from app.services.task_service import ALLOWED_TRANSITIONS, ensure_transition_allowed

TODO, IN_PROGRESS, IN_REVIEW, DONE = (
    TaskStatus.TODO,
    TaskStatus.IN_PROGRESS,
    TaskStatus.IN_REVIEW,
    TaskStatus.DONE,
)

# --- task status transitions ----------------------------------------------------

ALLOWED = {
    (TODO, IN_PROGRESS),
    (IN_PROGRESS, TODO),
    (IN_PROGRESS, IN_REVIEW),
    (IN_PROGRESS, DONE),
    (IN_REVIEW, IN_PROGRESS),
    (IN_REVIEW, DONE),
    (DONE, IN_PROGRESS),
}


@pytest.mark.parametrize("current", list(TaskStatus))
@pytest.mark.parametrize("new", list(TaskStatus))
def test_every_status_transition(current: TaskStatus, new: TaskStatus) -> None:
    if current is new or (current, new) in ALLOWED:
        ensure_transition_allowed(current, new)
    else:
        with pytest.raises(UnprocessableError) as exc:
            ensure_transition_allowed(current, new)
        assert exc.value.code == "INVALID_STATUS_TRANSITION"
        assert exc.value.details == [
            {
                "field": "body.status",
                "allowed": sorted(s.value for s in ALLOWED_TRANSITIONS[current]),
            }
        ]


def test_every_status_has_a_way_forward_and_back() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(TaskStatus)
    assert all(ALLOWED_TRANSITIONS[s] for s in TaskStatus)


# --- invitation expiry and state ------------------------------------------------

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _invitation(**overrides: object) -> Invitation:
    fields: dict[str, object] = {
        "organization_id": uuid.uuid4(),
        "email": "bob@example.com",
        "role": MembershipRole.MEMBER,
        "token_hash": "x" * 64,
        "expires_at": NOW + timedelta(hours=1),
    }
    return Invitation(**(fields | overrides))


def test_valid_invitation_passes() -> None:
    ensure_invitation_usable(_invitation(), "bob@example.com", NOW)


@pytest.mark.parametrize(
    ("expires_in", "usable"),
    [(timedelta(seconds=1), True), (timedelta(0), False), (timedelta(seconds=-1), False)],
)
def test_expiry_boundary(expires_in: timedelta, usable: bool) -> None:
    invitation = _invitation(expires_at=NOW + expires_in)
    if usable:
        ensure_invitation_usable(invitation, "bob@example.com", NOW)
    else:
        with pytest.raises(GoneError) as exc:
            ensure_invitation_usable(invitation, "bob@example.com", NOW)
        assert exc.value.code == "INVITATION_EXPIRED"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"revoked_at": NOW}, "INVITATION_REVOKED"),
        ({"accepted_at": NOW}, "INVITATION_ALREADY_USED"),
    ],
)
def test_used_or_revoked_invitations_are_gone(overrides: dict[str, object], code: str) -> None:
    with pytest.raises(GoneError) as exc:
        ensure_invitation_usable(_invitation(**overrides), "bob@example.com", NOW)
    assert exc.value.code == code


def test_wrong_email_is_checked_before_state() -> None:
    # Someone else holding a revoked, expired link learns nothing about its state.
    stale = _invitation(revoked_at=NOW, expires_at=NOW - timedelta(days=1))
    with pytest.raises(PermissionDeniedError) as exc:
        ensure_invitation_usable(stale, "mallory@example.com", NOW)
    assert exc.value.code == "INVITATION_EMAIL_MISMATCH"


# --- update rules (projects and tasks) ------------------------------------------


def test_version_must_match() -> None:
    ensure_version(3, 3)
    with pytest.raises(ConflictError) as exc:
        ensure_version(3, 2)
    assert exc.value.code == "VERSION_CONFLICT"
    assert exc.value.details == [{"field": "version", "current_version": 3}]


def test_project_update_requires_version() -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate({"name": "x"})
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate({"version": 0, "name": "x"})


def test_partial_update_reports_only_sent_fields() -> None:
    update = ProjectUpdate.model_validate({"version": 1, "description": None})
    assert update.changes() == {"version": 1, "description": None}  # explicit null kept


@pytest.mark.parametrize("field", ["name", "status", "workspace_id"])
def test_project_required_fields_cannot_be_nulled(field: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        ProjectUpdate.model_validate({"version": 1, field: None})


@pytest.mark.parametrize("field", ["assignee_id", "due_date", "description"])
def test_task_nullable_fields_can_be_cleared(field: str) -> None:
    assert TaskUpdate.model_validate({"version": 1, field: None}).changes()[field] is None


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_task_required_fields_cannot_be_nulled(field: str) -> None:
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"version": 1, field: None})


def test_update_bodies_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TaskUpdate.model_validate({"version": 1, "organization_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate({"version": 1, "nullable_fields": ["name"]})
