"""Migration compatibility: the migrated schema matches the models, and every revision
downgrades and upgrades cleanly, including the data rewrite in the week-3 migration."""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db import models  # noqa: F401  (register every table)
from app.db.base import Base
from app.db.session import engine
from tests.conftest import BACKEND_DIR, _test_db_url

WEEK3 = "745a13f70533"


@pytest.fixture
def alembic_config(migrated_database: None) -> Iterator[Config]:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", _test_db_url.replace("%", "%%"))
    engine.dispose()  # no pooled connections holding locks during DDL
    try:
        yield config
    finally:
        command.upgrade(config, "head")  # always leave the schema at head for other tests
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE users, organizations CASCADE"))


def test_models_match_migrated_schema(alembic_config: Config) -> None:
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    assert diff == []


def test_every_revision_downgrades_and_upgrades(alembic_config: Config) -> None:
    revisions = list(reversed(list(ScriptDirectory.from_config(alembic_config).walk_revisions())))
    assert len(revisions) >= 3
    command.downgrade(alembic_config, "base")
    for revision in revisions:
        command.upgrade(alembic_config, revision.revision)
        command.downgrade(alembic_config, "-1")
        command.upgrade(alembic_config, revision.revision)


def test_week3_downgrade_rewrites_in_review_tasks(alembic_config: Config) -> None:
    ids = {k: uuid.uuid4() for k in ("org", "ws", "project", "task")}
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO organizations (id, name, slug) VALUES (:org, 'M', 'mig')"), ids
        )
        conn.execute(
            text(
                "INSERT INTO workspaces (id, organization_id, name, slug) "
                "VALUES (:ws, :org, 'W', 'w')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, organization_id, workspace_id, name) "
                "VALUES (:project, :org, :ws, 'P')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO tasks (id, organization_id, project_id, title, status, priority) "
                "VALUES (:task, :org, :project, 'T', 'in_review', 'medium')"
            ),
            ids,
        )

    command.downgrade(alembic_config, f"{WEEK3}-1")  # old constraint has no 'in_review'
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM tasks WHERE id = :task"), ids).scalar()
    assert status == "in_progress"
