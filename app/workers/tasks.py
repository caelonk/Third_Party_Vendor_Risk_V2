"""Background tasks.

Phase 0 ships only a health-check task so the worker wiring is exercisable.
Phase 2 adds the real tasks: dispatch due CPE prefixes, incremental sync per
prefix, append risk snapshots, evaluate alert rules, and dispatch notifications.
"""
from __future__ import annotations

from .celery_app import celery_app


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    return "pong"
