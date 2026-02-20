from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Prefer repo-root `.env` so `docker compose` and `apps/api` share one config.
    # Keep local `.env` as a fallback for service-specific overrides.
    _REPO_ROOT = Path(__file__).resolve().parents[4]
    model_config = SettingsConfigDict(env_file=(_REPO_ROOT / ".env", ".env"), extra="ignore")

    VERSION: str = "0.1.0"
    APP_ENV: str = "dev"  # dev|test|prod
    DATABASE_URL: str = "postgresql+psycopg://tickets:tickets@localhost:5432/tickets_dev"

    API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000"

    JWT_SECRET: str = "change-me"
    ENCRYPTION_KEY_BASE64: str = "change-me-32-bytes-base64"

    # Auth / cookies
    ALLOW_DEV_LOGIN: bool = False
    SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 30  # 30 days
    SESSION_COOKIE_NAME: str = "oss_session"
    CSRF_COOKIE_NAME: str = "oss_csrf"
    CSRF_HEADER_NAME: str = "x-csrf-token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"  # lax|strict|none
    COOKIE_DOMAIN: str | None = None

    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY_ID: str = "minio"
    S3_SECRET_ACCESS_KEY: str = "minioadmin"
    S3_BUCKET: str = "tickets-blobs"
    BLOB_STORE: str = "s3"  # "s3" or "local"
    LOCAL_BLOB_DIR: str = "var/blobs"
    ATTACHMENT_DOWNLOAD_URL_TTL_SECONDS: int = 300

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    REQUEST_ID_HEADER: str = "x-request-id"
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 120
    ENABLE_PROMETHEUS_METRICS: bool = True
    PROMETHEUS_METRICS_PATH: str = "/metrics"
    ENABLE_OTEL_TRACING: bool = False
    OTEL_SERVICE_NAME: str = "oss-ticketing-api"
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: str = "http://localhost:4318/v1/traces"
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_TRACE_SAMPLE_RATIO: float = 1.0
    OTEL_EXCLUDED_URLS: str = "/healthz,/readyz,/metrics"
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'self'; "
        "img-src 'self' data: cid:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    @field_validator("COOKIE_DOMAIN", mode="before")
    @classmethod
    def _empty_cookie_domain_to_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("OTEL_TRACE_SAMPLE_RATIO")
    @classmethod
    def _validate_otel_sample_ratio(cls, v: float) -> float:
        if v < 0 or v > 1:
            raise ValueError("OTEL_TRACE_SAMPLE_RATIO must be between 0 and 1")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
