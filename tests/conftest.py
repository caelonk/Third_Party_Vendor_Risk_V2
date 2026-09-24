"""API test harness: an isolated in-memory SQLite database wired into the app via
dependency override, with per-user TestClients (each has its own cookie jar)."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base
from app.services import object_storage, oidc

API = "/api/v1"


class ApiHarness:
    """Spawns TestClients against one shared in-memory DB."""

    def __init__(self, app, session_factory):
        self.app = app
        self._session_factory = session_factory

    def client(self) -> TestClient:
        return TestClient(self.app)

    def db(self):
        """A session on the same in-memory DB, for arranging test data directly."""
        return self._session_factory()

    def register(
        self,
        email: str,
        password: str = "password123",
        *,
        name: str | None = None,
        org_name: str | None = None,
    ) -> tuple[TestClient, object]:
        """Register a user; return (authenticated client, response)."""
        c = self.client()
        payload = {"email": email, "password": password}
        if name is not None:
            payload["name"] = name
        if org_name is not None:
            payload["org_name"] = org_name
        resp = c.post(f"{API}/auth/register", json=payload)
        return c, resp


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")  # allow cookies over http testserver
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "x" * 40)
    # Never touch a real Redis (the Docker stack publishes one on localhost):
    # port 1 refuses instantly, so NVD throttles degrade to local pacing.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    # A developer's .env may hold real Google credentials: tests never use them.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("OIDC_DEV_PROVIDER", "false")
    get_settings.cache_clear()
    oidc.get_provider.cache_clear()
    object_storage.get_storage.cache_clear()

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite disables FK enforcement by default; turn it on so the tests exercise
    # the same referential integrity Postgres enforces in production.
    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_conn, _record):  # pragma: no cover - trivial wiring
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override_session():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    try:
        yield ApiHarness(app, TestingSession)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        get_settings.cache_clear()
        oidc.get_provider.cache_clear()
        object_storage.get_storage.cache_clear()
