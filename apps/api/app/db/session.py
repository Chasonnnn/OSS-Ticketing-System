from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _make_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return _make_engine()


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker:
    engine = get_engine()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
