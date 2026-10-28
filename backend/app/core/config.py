from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root holds the single .env shared by docker-compose and the backend.
REPO_ROOT = Path(__file__).resolve().parents[3]

_PLACEHOLDER_MARKERS = ("change", "replace", "secret", "example")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors land in start-up logs: never echo the raw values (secrets).
        hide_input_in_errors=True,
    )

    app_name: str = "TeamFlow API"
    environment: Literal["development", "test", "production"] = "development"

    database_url: str
    test_database_url: str | None = None
    db_pool_size: int = Field(default=5, gt=0, le=50)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    # Recycle before typical server/LB idle timeouts silently drop connections.
    db_pool_recycle_seconds: int = Field(default=1800, gt=0)
    # A runaway query must not hold a connection (and its locks) forever.
    db_statement_timeout_ms: int = Field(default=15_000, ge=0)

    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0, le=60)
    refresh_token_expire_days: int = Field(default=7, gt=0, le=90)
    invitation_expire_hours: int = Field(default=72, gt=0, le=24 * 30)

    redis_url: str = "redis://127.0.0.1:6380/0"
    test_redis_url: str | None = None
    # Redis is an optimization: fail fast and fall back rather than stall requests.
    redis_socket_timeout_seconds: float = 0.25
    cache_ttl_seconds: int = Field(default=60, gt=0, le=3600)
    rate_limit_enabled: bool = True

    cookie_secure: bool = True
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_path: str = "/api/v1/auth"

    log_format: Literal["text", "json"] = "text"
    # None = on everywhere except production.
    docs_enabled: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def show_docs(self) -> bool:
        return not self.is_production if self.docs_enabled is None else self.docs_enabled

    @model_validator(mode="after")
    def _refuse_unsafe_production_config(self) -> "Settings":
        # Fail at start-up, loudly, instead of running production with dev settings.
        if not self.is_production:
            return self
        problems = []
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (refresh cookie over HTTPS only)")
        secret = self.jwt_secret_key.get_secret_value()
        if len(secret) < 64 or any(m in secret.lower() for m in _PLACEHOLDER_MARKERS):
            problems.append("JWT_SECRET_KEY must be a random value of at least 64 characters")
        if not self.rate_limit_enabled:
            problems.append("RATE_LIMIT_ENABLED must be true")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
