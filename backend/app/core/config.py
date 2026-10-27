from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root holds the single .env shared by docker-compose and the backend.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TeamFlow API"
    environment: Literal["development", "test", "production"] = "development"

    database_url: str
    test_database_url: str | None = None

    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0, le=60)
    refresh_token_expire_days: int = Field(default=7, gt=0, le=90)

    cookie_secure: bool = True
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_path: str = "/api/v1/auth"


@lru_cache
def get_settings() -> Settings:
    return Settings()
