import json
import logging
import secrets
import sys

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import JsonFormatter

STRONG_SECRET = secrets.token_urlsafe(64)


def _production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+psycopg://u:p@db/teamflow",
        "jwt_secret_key": STRONG_SECRET,
        "cookie_secure": True,
        "rate_limit_enabled": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_safe_production_config_is_accepted_and_hides_docs() -> None:
    settings = _production()
    assert settings.is_production
    assert not settings.show_docs


def test_docs_can_be_turned_on_explicitly_in_production() -> None:
    assert _production(docs_enabled=True).show_docs


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"jwt_secret_key": "x" * 40}, "JWT_SECRET_KEY"),
        ({"jwt_secret_key": "replace-with-a-long-random-secret-" + "a" * 40}, "JWT_SECRET_KEY"),
        ({"rate_limit_enabled": False}, "RATE_LIMIT_ENABLED"),
    ],
)
def test_unsafe_production_config_refuses_to_start(
    overrides: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValidationError, match=problem):
        _production(**overrides)


def test_development_allows_local_conveniences() -> None:
    settings = _production(environment="development", cookie_secure=False, jwt_secret_key="x" * 32)
    assert settings.show_docs


def test_json_log_lines_are_parseable_and_carry_request_id() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "app.test", logging.ERROR, __file__, 1, "failed %s", ("x",), exc_info
    )
    record.request_id = "req-1"
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "failed x"
    assert entry["level"] == "ERROR"
    assert entry["request_id"] == "req-1"
    assert "RuntimeError: boom" in entry["exception"]


def test_config_errors_never_echo_secret_values() -> None:
    weak = "x" * 40
    with pytest.raises(ValidationError) as excinfo:
        _production(jwt_secret_key=weak)
    assert weak not in str(excinfo.value)
