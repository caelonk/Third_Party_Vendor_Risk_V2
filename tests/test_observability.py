"""Request IDs, structured access logs, the JSON formatter, and Sentry wiring."""
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app import observability as obs
from app.config import Settings

API = "/api/v1"
HEX32 = re.compile(r"^[0-9a-f]{32}$")


# --------------------------------------------------------------------------- #
# Request IDs                                                                 #
# --------------------------------------------------------------------------- #
def test_every_response_gets_a_request_id(api):
    c = api.client()
    ok = c.get("/healthz")
    missing = c.get(f"{API}/orgs")  # 401, still tagged
    assert HEX32.match(ok.headers["X-Request-ID"])
    assert HEX32.match(missing.headers["X-Request-ID"])
    assert ok.headers["X-Request-ID"] != missing.headers["X-Request-ID"]


def test_wellformed_inbound_id_is_reused_malformed_is_replaced(api):
    c = api.client()
    good = "edge-4f2a9c1b"
    assert c.get("/healthz", headers={"X-Request-ID": good}).headers["X-Request-ID"] == good
    for bad in ("short", "has spaces in it", "x" * 65, "semi;colon-12345"):
        got = c.get("/healthz", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
        assert got != bad and HEX32.match(got)


def test_unhandled_error_returns_500_carrying_the_request_id(api, caplog):
    @api.app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    c = TestClient(api.app)
    with caplog.at_level(logging.ERROR, logger="app"):
        res = c.get("/boom")
    assert res.status_code == 500
    rid = res.headers["X-Request-ID"]
    assert res.json() == {"detail": "Internal server error", "request_id": rid}
    assert "kaboom" not in res.text  # no internals leaked to the client
    err = next(r for r in caplog.records if r.getMessage() == "unhandled error")
    assert err.exc_info and "kaboom" in str(err.exc_info[1])


# --------------------------------------------------------------------------- #
# Access log                                                                  #
# --------------------------------------------------------------------------- #
def test_access_log_has_path_without_query_and_the_request_id(api, caplog):
    client, _ = api.register("obs@acme.io")
    oid = client.get(f"{API}/orgs").json()[0]["id"]
    caplog.handler.addFilter(obs.ContextFilter())  # what the real handler does
    with caplog.at_level(logging.INFO, logger="app.access"):
        res = client.get(f"{API}/orgs/{oid}/vendors?token=supersecret123")

    line = next(r for r in caplog.records if r.name == "app.access")
    assert line.http_path == f"{API}/orgs/{oid}/vendors"
    assert line.http_status == 200 and line.http_method == "GET"
    assert isinstance(line.duration_ms, float)
    assert line.request_id == res.headers["X-Request-ID"]
    assert "supersecret123" not in line.getMessage() + json.dumps(vars(line), default=str)


def test_health_probes_log_at_debug(api, caplog):
    with caplog.at_level(logging.DEBUG, logger="app.access"):
        api.client().get("/healthz")
    probe = next(r for r in caplog.records if r.name == "app.access")
    assert probe.levelno == logging.DEBUG


# --------------------------------------------------------------------------- #
# Formatters                                                                  #
# --------------------------------------------------------------------------- #
def _record(**extra) -> logging.LogRecord:
    rec = logging.makeLogRecord({"name": "app.test", "levelno": logging.WARNING,
                                 "levelname": "WARNING", "msg": "hello %s", "args": ("world",)})
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_emits_one_parseable_object():
    token = obs.request_id_var.set("req-12345678")
    try:
        rec = _record(vendor_id=7)
        obs.ContextFilter().filter(rec)
        try:
            raise ValueError("nope")
        except ValueError:
            import sys

            rec.exc_info = sys.exc_info()
        out = json.loads(obs.JsonFormatter().format(rec))
    finally:
        obs.request_id_var.reset(token)
    assert out["level"] == "warning" and out["msg"] == "hello world"
    assert out["request_id"] == "req-12345678" and out["vendor_id"] == 7
    assert "ValueError: nope" in out["exc"]
    assert "task_id" not in out  # absent ids are omitted, not null


def test_json_formatter_drops_uvicorn_color_duplicate():
    rec = _record(color_message="\x1b[1mhello\x1b[0m")
    assert "color_message" not in json.loads(obs.JsonFormatter().format(rec))


def test_text_formatter_shows_ids_inline():
    rec = _record()
    rec.request_id, rec.task_id = "req-12345678", None
    assert "[req-12345678] hello world" in obs.TextFormatter().format(rec)


def test_log_format_auto_is_json_only_in_production():
    assert Settings(env="production").log_json is True
    assert Settings(env="development").log_json is False
    assert Settings(env="development", log_format="json").log_json is True


# --------------------------------------------------------------------------- #
# Sentry                                                                      #
# --------------------------------------------------------------------------- #
def test_scrub_event_drops_secrets_and_tags_request_id():
    token = obs.request_id_var.set("req-abcdef12")
    try:
        event = obs.scrub_event({"request": {
            "cookies": {"access_token": "jwt"},
            "data": {"password": "hunter2"},
            "query_string": "token=abc",
            "headers": {"Cookie": "a=b", "Authorization": "Bearer x", "User-Agent": "ua"},
        }})
    finally:
        obs.request_id_var.reset(token)
    req = event["request"]
    assert "cookies" not in req and "data" not in req and "query_string" not in req
    assert req["headers"] == {"User-Agent": "ua"}
    assert event["tags"]["request_id"] == "req-abcdef12"


def test_sentry_is_inert_without_a_dsn(monkeypatch):
    calls = []
    monkeypatch.setattr(obs.sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert obs.init_sentry(Settings(sentry_dsn=None), component="api") is False
    assert calls == []


def test_sentry_init_uses_scrubber_and_no_pii(monkeypatch):
    calls = []
    monkeypatch.setattr(obs.sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(obs.sentry_sdk, "set_tag", lambda *a: None)
    enabled = obs.init_sentry(
        Settings(sentry_dsn="https://public@example.invalid/1", env="production", app_release="abc123"),
        component="worker",
    )
    assert enabled is True
    kw = calls[0]
    assert kw["before_send"] is obs.scrub_event and kw["send_default_pii"] is False
    assert kw["environment"] == "production" and kw["release"] == "abc123"


@pytest.fixture(autouse=True)
def _reset_ids():
    yield
    obs.request_id_var.set(None)
    obs.task_id_var.set(None)
