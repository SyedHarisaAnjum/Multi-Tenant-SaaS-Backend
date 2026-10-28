from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=_settings.db_pool_recycle_seconds,
    pool_timeout=10,
    connect_args={
        "options": f"-c statement_timeout={_settings.db_statement_timeout_ms}",
        "connect_timeout": 5,
        "application_name": "teamflow-api",
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            # Any failure mid-request discards partial work (e.g. a half-done
            # ownership transfer) before the error response is produced.
            session.rollback()
            raise
