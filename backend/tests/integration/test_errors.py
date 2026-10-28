"""Phase 11: one error shape, request ids, and nothing internal leaking to clients."""

import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.main import app
from app.services.workspace_service import WorkspaceService
from tests.conftest import Tenants

SECRET_PASSWORD = "hunter2"  # too short: triggers validation


def _assert_error_shape(response: object, status: int, code: str) -> dict:  # type: ignore[type-arg]
    assert response.status_code == status  # type: ignore[attr-defined]
    error = response.json()["error"]  # type: ignore[attr-defined]
    assert error["code"] == code
    assert error["message"]
    assert error["request_id"] == response.headers["x-request-id"]  # type: ignore[attr-defined]
    return error  # type: ignore[no-any-return]


@pytest.fixture
def lenient_client(db: Session, client: TestClient) -> Iterator[TestClient]:
    """Returns 500 responses instead of re-raising, like a real server would."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_validation_error_does_not_echo_input(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": SECRET_PASSWORD}
    )
    error = _assert_error_shape(response, 422, "VALIDATION_ERROR")
    assert {d["field"] for d in error["details"]} == {"body.email", "body.password"}
    assert SECRET_PASSWORD not in response.text
    assert "input" not in response.text


def test_authentication_error(client: TestClient) -> None:
    error = _assert_error_shape(client.get("/api/v1/auth/me"), 401, "NOT_AUTHENTICATED")
    assert "detail" not in error


def test_authorization_error(client: TestClient, tenants: Tenants) -> None:
    response = client.patch(
        f"/api/v1/organizations/{tenants.acme}", json={"name": "x"}, headers=tenants.viewer.headers
    )
    _assert_error_shape(response, 403, "FORBIDDEN")


def test_missing_resource_has_specific_code(client: TestClient, tenants: Tenants) -> None:
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=tenants.owner.headers)
    _assert_error_shape(response, 404, "PROJECT_NOT_FOUND")


def test_duplicate_resource(client: TestClient, tenants: Tenants) -> None:
    response = client.post(
        "/api/v1/organizations",
        json={"name": "Acme", "slug": "acme"},
        headers=tenants.owner.headers,
    )
    _assert_error_shape(response, 409, "SLUG_TAKEN")


def test_unknown_route_and_wrong_method(client: TestClient) -> None:
    _assert_error_shape(client.get("/api/v1/nope"), 404, "NOT_FOUND")
    _assert_error_shape(client.delete("/health"), 405, "METHOD_NOT_ALLOWED")


def test_unanticipated_constraint_violation_hides_sql(
    lenient_client: TestClient, tenants: Tenants, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_: object) -> None:
        raise IntegrityError("INSERT INTO workspaces (secret_column) VALUES (...)", {}, Exception())

    monkeypatch.setattr(WorkspaceService, "create", explode)
    response = lenient_client.post(
        f"/api/v1/organizations/{tenants.acme}/workspaces",
        json={"name": "x", "slug": "xyz"},
        headers=tenants.owner.headers,
    )
    _assert_error_shape(response, 409, "CONFLICT")
    assert "INSERT" not in response.text and "secret_column" not in response.text


def test_unexpected_error_is_generic_and_logged_with_request_id(
    lenient_client: TestClient,
    tenants: Tenants,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def explode(*_: object) -> None:
        raise RuntimeError("db password is postgres://admin:s3cret@10.0.0.5")

    monkeypatch.setattr(WorkspaceService, "create", explode)
    with caplog.at_level(logging.ERROR):
        response = lenient_client.post(
            f"/api/v1/organizations/{tenants.acme}/workspaces",
            json={"name": "x", "slug": "xyz"},
            headers={**tenants.owner.headers, "X-Request-ID": "trace-me-123"},
        )
    error = _assert_error_shape(response, 500, "INTERNAL_ERROR")
    assert error["request_id"] == "trace-me-123"
    assert "s3cret" not in response.text and "Traceback" not in response.text

    record = next(r for r in caplog.records if r.levelno == logging.ERROR)
    assert record.request_id == "trace-me-123"  # type: ignore[attr-defined]
    assert record.exc_info is not None  # full stack trace goes to the log only


def test_request_id_is_echoed_or_generated(client: TestClient) -> None:
    echoed = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["x-request-id"] == "abc-123"

    generated = client.get("/health")
    assert len(generated.headers["x-request-id"]) == 32

    # Unsafe client values (log injection, oversized) are replaced, not trusted.
    hostile = client.get("/health", headers={"X-Request-ID": "x\r\nFAKE LOG LINE" + "a" * 100})
    assert hostile.headers["x-request-id"] != "x"
    assert len(hostile.headers["x-request-id"]) == 32
