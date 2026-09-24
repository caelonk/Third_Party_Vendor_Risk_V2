"""Gunicorn settings for the API container (uvicorn workers behind nginx).

Logging is configured here, in the master, so even gunicorn's and uvicorn's own
startup lines come out in the app's format (JSON in production) — the app's
lifespan hook alone runs too late to catch them.
"""
import multiprocessing
import os

from app.config import get_settings

bind = os.getenv("BIND", "0.0.0.0:8000")
worker_class = "uvicorn_worker.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", str(min(2 * multiprocessing.cpu_count() + 1, 8))))

# On-demand sync makes paced NVD calls synchronously; give requests room.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "150"))
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to bound slow memory growth.
max_requests = 2000
max_requests_jitter = 200

# Only the nginx container reaches us (published port is 127.0.0.1-only), so
# trust its X-Forwarded-* headers.
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

accesslog = None  # the app writes one structured access line per request
errorlog = "-"

_settings = get_settings()
_formatter = "JsonFormatter" if _settings.log_json else "TextFormatter"

logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"ctx": {"()": "app.observability.ContextFilter"}},
    "formatters": {"default": {"()": f"app.observability.{_formatter}"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
            "filters": ["ctx"],
        }
    },
    "root": {"level": _settings.log_level.upper(), "handlers": ["stdout"]},
    "loggers": {
        "gunicorn.error": {"level": "INFO", "handlers": [], "propagate": True},
        "gunicorn.access": {"handlers": [], "propagate": False},
        "uvicorn.error": {"handlers": [], "propagate": True},
        "uvicorn.access": {"handlers": [], "propagate": False},
    },
}
