from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app import main
from app.db.session import get_db


def test_liveness_has_no_dependencies(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health", "/health/ready"])
def test_readiness_checks_database_and_redis(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


def test_readiness_stays_ready_without_redis(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DeadRedis:
        def ping(self) -> None:
            raise RedisConnectionError("down")

    monkeypatch.setattr(main, "get_redis", lambda: DeadRedis())
    response = client.get("/health/ready")
    # Redis is an optimization: the API still serves (cache falls back, limits fail open).
    assert response.status_code == 200
    assert response.json()["redis"] == "unreachable"


def test_readiness_fails_without_database(client: TestClient) -> None:
    class DeadSession:
        def execute(self, *_: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def dead_db() -> Iterator[DeadSession]:
        yield DeadSession()

    previous = main.app.dependency_overrides[get_db]
    main.app.dependency_overrides[get_db] = dead_db
    try:
        response = client.get("/health/ready")
    finally:
        main.app.dependency_overrides[get_db] = previous
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unreachable", "redis": "ok"}
