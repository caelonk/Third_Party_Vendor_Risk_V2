"""SQLAlchemy engine and session wiring (sync engine + psycopg3).

The domain core is synchronous and the NVD client is blocking, so the web layer
uses a synchronous engine and a request-scoped session (simpler and a better fit
for the Celery worker, which shares this module).

The engine is created lazily so importing this module never requires the DBAPI
(psycopg) or opens a connection — only the first real use does.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def _get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, future=True
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it."""
    session = _get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
