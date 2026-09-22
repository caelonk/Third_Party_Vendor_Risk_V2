"""App-factory smoke tests using the FastAPI TestClient (no DB required)."""
from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_ok():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_reports_name_and_version():
    client = TestClient(create_app())
    body = client.get("/").json()
    assert body["name"] == "vendor-risk"
    assert body["version"] == "0.1.0"


def test_openapi_served():
    client = TestClient(create_app())
    assert client.get("/api/openapi.json").status_code == 200
