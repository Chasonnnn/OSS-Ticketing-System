from __future__ import annotations

import os
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import Session

from alembic import command


def _make_admin_url(url: URL) -> URL:
    # "postgres" is present in the official image and works for admin tasks.
    return url.set(database="postgres")


def _make_test_db_name() -> str:
    return f"oss_tickets_test_{uuid.uuid4().hex}"


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> None:
    # Default points at the dev DB, but we always create an isolated database for tests.
    if "DATABASE_URL" in os.environ:
        base_url = os.environ["DATABASE_URL"]
    else:
        # Load repo-root `.env` (via Settings) so local dev can move Postgres off :5432.
        from app.core.config import get_settings

        base_url = get_settings().DATABASE_URL
    url = make_url(base_url)

    if url.host not in {"localhost", "127.0.0.1", None}:
        raise RuntimeError(
            "Refusing to run tests against a non-local DATABASE_URL host. "
            "Set DATABASE_URL to a local/dev Postgres instance."
        )

    db_name = _make_test_db_name()
    admin_engine = create_engine(
        _make_admin_url(url), isolation_level="AUTOCOMMIT", pool_pre_ping=True
    )

    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    test_url = url.set(database=db_name).render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = test_url
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("ALLOW_DEV_LOGIN", "true")
    os.environ.setdefault("COOKIE_SECURE", "false")

    # Clear cached settings/engines so imports inside the test session use the test DB.
    from app.core.config import get_settings
    from app.db.session import get_engine, get_sessionmaker

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(alembic_ini))
    command.upgrade(cfg, "head")

    yield

    # Ensure connection pools to the test DB are closed before dropping.
    with suppress(Exception):
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    get_settings.cache_clear()

    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name AND pid <> pg_backend_pid();
                """
            ),
            {"db_name": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))

    admin_engine.dispose()


@pytest.fixture()
def db_session() -> Session:
    from app.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
