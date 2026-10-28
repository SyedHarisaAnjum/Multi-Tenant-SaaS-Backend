import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings

# Point the app at the test database and test Redis *before* anything connects.
_settings = Settings()  # type: ignore[call-arg]
_test_db_url = os.environ.get("TEST_DATABASE_URL") or _settings.test_database_url
_test_redis_url = os.environ.get("TEST_REDIS_URL") or _settings.test_redis_url
if not _test_db_url or not _test_redis_url:
    raise RuntimeError("Set TEST_DATABASE_URL and TEST_REDIS_URL to run the test suite.")
os.environ["DATABASE_URL"] = _test_db_url
os.environ["REDIS_URL"] = _test_redis_url
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"  # TestClient talks plain http
get_settings.cache_clear()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core import security  # noqa: E402
from app.core.rate_limit import RateLimiter, get_rate_limiter  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import (  # noqa: E402
    Actor,
    add_member,
    create_actor,
    create_org,
    create_project,
    create_workspace,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Production Argon2 parameters are deliberately slow; tests hash dozens of passwords.
# Still Argon2id, just cheap. (The hash encodes its own parameters, so verify works either way.)
security._password_hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Rebuild the schema from migrations alone, proving a clean DB can be created."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", _test_db_url.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture
def clean_redis() -> None:
    """The DB is rolled back per test; Redis isn't, so wipe the test Redis database."""
    get_redis().flushdb()


# Unit tests (tests/unit) use none of the fixtures below, so they run without
# PostgreSQL or Redis. Anything touching the database pulls in the migrated schema
# and a clean Redis through these dependencies.
@pytest.fixture
def db(migrated_database: None, clean_redis: None) -> Iterator[Session]:
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
    def override_get_db() -> Iterator[Session]:
        try:
            yield db
        except Exception:
            db.rollback()  # mirrors get_db; in this fixture it rolls back to the savepoint
            raise

    app.dependency_overrides[get_db] = override_get_db
    # The suite registers hundreds of users from one IP; rate-limit tests opt back in.
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(get_redis(), enabled=False)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@dataclass(frozen=True)
class Tenants:
    """Two organizations. Acme has one user per role; Globex is owned by Mallory."""

    acme: uuid.UUID
    owner: Actor
    admin: Actor
    member: Actor
    viewer: Actor
    globex: uuid.UUID
    mallory: Actor


@pytest.fixture
def tenants(client: TestClient) -> Tenants:
    owner = create_actor(client, "owner@acme.com")
    admin = create_actor(client, "admin@acme.com")
    member = create_actor(client, "member@acme.com")
    viewer = create_actor(client, "viewer@acme.com")
    mallory = create_actor(client, "mallory@globex.com")

    acme = create_org(client, owner, "acme")
    add_member(client, owner, acme, admin, "admin")
    add_member(client, owner, acme, member, "member")
    add_member(client, owner, acme, viewer, "viewer")
    globex = create_org(client, mallory, "globex")

    return Tenants(acme, owner, admin, member, viewer, globex, mallory)


@dataclass(frozen=True)
class Board:
    workspace_id: str
    project_id: str


@pytest.fixture
def acme_board(client: TestClient, tenants: Tenants) -> Board:
    workspace = create_workspace(client, tenants.owner, tenants.acme, "engineering")
    project = create_project(client, tenants.member, tenants.acme, workspace["id"], "Launch")
    return Board(workspace_id=workspace["id"], project_id=project["id"])


@pytest.fixture
def globex_board(client: TestClient, tenants: Tenants) -> Board:
    workspace = create_workspace(client, tenants.mallory, tenants.globex, "secret-lab")
    project = create_project(client, tenants.mallory, tenants.globex, workspace["id"], "Secret")
    return Board(workspace_id=workspace["id"], project_id=project["id"])
