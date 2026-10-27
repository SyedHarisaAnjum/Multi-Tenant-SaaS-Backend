import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings

# Point the app at the test database *before* anything creates an engine.
_test_db_url = os.environ.get("TEST_DATABASE_URL") or Settings().test_database_url  # type: ignore[call-arg]
if not _test_db_url:
    raise RuntimeError("Set TEST_DATABASE_URL to run the test suite.")
os.environ["DATABASE_URL"] = _test_db_url
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"  # TestClient talks plain http
get_settings.cache_clear()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Rebuild the schema from migrations alone, proving a clean DB can be created."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", _test_db_url.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture
def db() -> Iterator[Session]:
    """Each test runs in an outer transaction that is rolled back afterwards.

    Code under test may call commit(); with create_savepoint those commits only
    release savepoints inside the outer transaction.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
