"""Celery application.

Redis is the broker and result backend. The worker imports the shared ``core``
package (scoring, parser, nvd_client, sync) and the ``app`` persistence layer, so
background sync/snapshot/alert/export tasks run the exact same logic as the API.

Phase 2 adds the Beat schedule (a single dispatcher on a cron) and the real
tasks; this module is the wiring those attach to.
"""
from __future__ import annotations

from celery import Celery

from ..config import get_settings

settings = get_settings()

celery_app = Celery(
    "vendor_risk",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
)

# Beat: a single dispatcher on a cron. It selects due vendors, dedupes them to
# CPE prefixes, and fans out one incremental ``sync_prefix`` task per prefix.
celery_app.conf.beat_schedule = {
    "dispatch-due-syncs": {
        "task": "app.workers.tasks.dispatch_due_syncs",
        "schedule": float(settings.beat_dispatch_interval_seconds),
    }
}
