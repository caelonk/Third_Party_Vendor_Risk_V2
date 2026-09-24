"""Celery application.

Redis is the broker and result backend. The worker imports the shared ``core``
package (scoring, parser, nvd_client, sync) and the ``app`` persistence layer, so
background sync/snapshot/alert/export tasks run the exact same logic as the API.

Phase 2 adds the Beat schedule (a single dispatcher on a cron) and the real
tasks; this module is the wiring those attach to.
"""
from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging, task_postrun, task_prerun

from ..config import get_settings
from ..observability import configure_logging, init_sentry, task_id_var

settings = get_settings()
init_sentry(settings, component="worker")  # no-op unless SENTRY_DSN is set


@setup_logging.connect
def _configure_logging(**_kwargs: object) -> None:
    # Connecting this signal stops Celery hijacking the root logger; worker and
    # beat then log through the same JSON/text handler as the API.
    configure_logging(settings)


@task_prerun.connect
def _bind_task_id(task_id: str | None = None, **_kwargs: object) -> None:
    task_id_var.set(task_id)


@task_postrun.connect
def _unbind_task_id(**_kwargs: object) -> None:
    task_id_var.set(None)

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
