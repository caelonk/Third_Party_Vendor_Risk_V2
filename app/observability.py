"""Structured logging, request IDs, and Sentry — one place for observability.

* Every HTTP request gets a request ID (reusing a well-formed inbound
  ``X-Request-ID``, else a fresh one). It is echoed on the response and attached
  to every log line emitted while handling the request; Celery tasks get their
  task id the same way.
* Logs are JSON in production (one object per line, easy to ship/query) and
  readable text in development. One access line per request records method,
  path, status, and duration — the path only, never the query string or body,
  which can carry search terms or tokens.
* Sentry is fully inert unless ``SENTRY_DSN`` is set. When enabled, cookies,
  auth headers, and request bodies are scrubbed before anything leaves the box.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
task_id_var: ContextVar[str | None] = ContextVar("task_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATHS = {"/healthz", "/readyz"}  # probe noise -> DEBUG

access_log = logging.getLogger("app.access")
_log = logging.getLogger("app")

# Attributes every LogRecord has; anything else on a record came from `extra=`.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {
    "message", "asctime", "request_id", "task_id", "ctx",
    "color_message",  # uvicorn's ANSI-colored duplicate of the message
}


# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
class ContextFilter(logging.Filter):
    """Stamp the current request/task id onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.task_id = task_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("request_id", "task_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s %(ctx)s%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        ids = [i for i in (getattr(record, "request_id", None), getattr(record, "task_id", None)) if i]
        record.ctx = f"[{' '.join(ids)}] " if ids else ""
        return super().format(record)


def configure_logging(settings: Settings) -> None:
    """Route everything (app, uvicorn, celery) through one formatted stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_json else TextFormatter())
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())

    for name in ("uvicorn", "uvicorn.error", "gunicorn.error", "celery"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    # Our middleware writes the (structured) access line; drop the duplicate text one.
    for name in ("uvicorn.access", "gunicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = False


# --------------------------------------------------------------------------- #
# Request context middleware (pure ASGI: no BaseHTTPMiddleware pitfalls)      #
# --------------------------------------------------------------------------- #
def _inbound_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name.lower() == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            return candidate if _VALID_REQUEST_ID.match(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = _inbound_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, rid)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            _log.exception("unhandled error")
            sentry_sdk.capture_exception()  # no-op when Sentry is disabled
            if response_started:
                raise  # too late to send a clean 500
            # Answer here rather than letting Starlette's outer error handler do it,
            # so the 500 — the response users most need to quote — carries the id.
            body = json.dumps({"detail": "Internal server error", "request_id": rid}).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            path = scope.get("path", "")
            access_log.log(
                logging.DEBUG if path in _QUIET_PATHS else logging.INFO,
                "%s %s %s",
                scope.get("method"),
                path,
                status,
                extra={
                    "http_method": scope.get("method"),
                    "http_path": path,  # path only: query strings can carry tokens
                    "http_status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)


# --------------------------------------------------------------------------- #
# Sentry                                                                      #
# --------------------------------------------------------------------------- #
_SENSITIVE_HEADERS = {"cookie", "authorization", "set-cookie", "x-api-key", "apikey"}


def scrub_event(event: dict, _hint: dict | None = None) -> dict:
    """Sentry before_send: drop cookies, auth headers, and bodies; tag request id."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        request.pop("data", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS
            }
    rid = request_id_var.get()
    if rid:
        event.setdefault("tags", {})["request_id"] = rid
    return event


def init_sentry(settings: Settings, *, component: str) -> bool:
    """Initialize Sentry if a DSN is configured. Returns whether it was enabled."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.env,
        release=settings.app_release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=scrub_event,  # type: ignore[arg-type]
    )
    sentry_sdk.set_tag("component", component)
    return True
