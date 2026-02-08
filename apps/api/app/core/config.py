from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Prefer repo-root `.env` so `docker compose` and `apps/api` share one config.
    # Keep local `.env` as a fallback for service-specific overrides.
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore")

    VERSION: str = "0.1.0"
    DATABASE_URL: str = "postgresql+psycopg://tickets:tickets@localhost:5432/tickets_dev"

    API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"

    JWT_SECRET: str = "change-me"
    ENCRYPTION_KEY_BASE64: str = "change-me-32-bytes-base64"

    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY_ID: str = "minio"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET: str = "tickets-blobs"
    BLOB_STORE: str = "s3"  # "s3" or "local"
    LOCAL_BLOB_DIR: str = "var/blobs"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
