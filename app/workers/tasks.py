"""Background tasks.

* ``ping`` — health check, keeps the worker wiring exercisable.
* ``dispatch_due_syncs`` — Beat fires this on a cron; it selects due vendors,
  dedupes them to CPE prefixes, and fans out one ``sync_prefix`` task per prefix.
* ``sync_prefix`` — syncs one prefix from NVD (rate-limited across every process
  by a per-key Redis token bucket) and finalizes each of its due vendors.
* ``run_export`` — renders one queued portfolio export into object storage.
* ``purge_exports`` — Beat: deletes exports past retention, fails stuck jobs.

Queues: ``sync`` carries incremental syncs; ``backfill`` carries a prefix's
first (expensive) pull and is served by its own worker, so a large import can
never occupy the slots that keep existing vendors current. Backfills also draw
NVD tokens with a reserve (see app.services.nvd_limits).

The real work lives in :mod:`app.services.scheduled_sync_service`; these tasks
are the thin Celery/Redis/session shell around it.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..db import session_scope
from ..services import export_service, object_storage
from ..services import scheduled_sync_service as sched
from ..services.scheduled_sync_service import PrefixWork
from .celery_app import celery_app

log = logging.getLogger(__name__)

QUEUE_SYNC = "sync"
QUEUE_BACKFILL = "backfill"


def queue_for(backfill: bool) -> str:
    return QUEUE_BACKFILL if backfill else QUEUE_SYNC


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="app.workers.tasks.dispatch_due_syncs")
def dispatch_due_syncs() -> dict:
    """Beat entrypoint: enqueue one ``sync_prefix`` task per due CPE prefix."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    counts = {QUEUE_SYNC: 0, QUEUE_BACKFILL: 0}
    with session_scope() as db:
        for work in sched.plan_due_work(db, now):
            # JSON transport: send org groups as [org_id, [vendor_ids]] pairs.
            groups = [[org_id, ids] for org_id, ids in work.vendors_by_org.items()]
            queue = queue_for(work.backfill)
            sync_prefix.apply_async(
                args=[work.prefix, groups], kwargs={"backfill": work.backfill}, queue=queue
            )
            counts[queue] += 1
    log.info(
        "dispatch_due_syncs: enqueued %d incremental + %d backfill prefix task(s)",
        counts[QUEUE_SYNC], counts[QUEUE_BACKFILL],
        extra={"sync_tasks": counts[QUEUE_SYNC], "backfill_tasks": counts[QUEUE_BACKFILL]},
    )
    return {"prefixes_dispatched": sum(counts.values()), **counts}


@celery_app.task(
    name="app.workers.tasks.sync_prefix",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def sync_prefix(self, prefix: str, groups: list, backfill: bool = False) -> dict:
    """Sync one CPE prefix and its due vendors (across orgs sharing the prefix).

    A per-prefix Redis lock makes same-prefix runs mutually exclusive across
    workers: a second dispatch (e.g. an overlapping Beat tick) that lands the
    same prefix skips rather than racing on the shared cache and watermark.
    """
    import redis as redis_lib

    settings = get_settings()
    client = redis_lib.from_url(settings.redis_url)

    # timeout auto-expires the lock if a worker dies mid-sync; comfortably longer
    # than a paced NVD pull.
    lock = client.lock(f"nvd:synclock:{prefix}", timeout=900, blocking=False)
    if not lock.acquire(blocking=False):
        log.info("sync_prefix(%s): already running elsewhere; skipping", prefix)
        return {"prefix": prefix, "skipped": True}

    work = PrefixWork(
        prefix=prefix,
        vendors_by_org={int(org_id): list(ids) for org_id, ids in groups},
        backfill=backfill,
    )
    fetch_prefix = sched.build_live_fetch_prefix(backfill=backfill)

    try:
        with session_scope() as db:
            result = sched.sync_prefix(db, work, fetch_prefix=fetch_prefix)
    except Exception as exc:  # transient NVD/Redis/DB failure — let Celery retry
        log.warning("sync_prefix(%s) failed: %s; retrying", prefix, exc)
        # Pin the queue: a retried backfill must not come back via the sync queue.
        raise self.retry(exc=exc, queue=queue_for(backfill)) from exc
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 — lock may have already expired
            pass

    log.info(
        "sync_prefix(%s): fetched=%s synced=%d failed=%d backfill=%s",
        prefix, result.fetched, result.vendors_synced, result.vendors_failed, backfill,
    )
    return {
        "prefix": result.prefix,
        "fetched": result.fetched,
        "vendors_synced": result.vendors_synced,
        "vendors_failed": result.vendors_failed,
        "error": result.error,
    }


@celery_app.task(name="app.workers.tasks.run_export")
def run_export(job_id: int) -> dict:
    """Render one export. No Celery retry: a failure is recorded on the job, and
    the user simply requests a new export."""
    with session_scope() as db:
        job = export_service.run_job(db, job_id, object_storage.get_storage())
        return {"job_id": job_id, "status": job.status.value if job else "missing"}


@celery_app.task(name="app.workers.tasks.purge_exports")
def purge_exports() -> dict:
    with session_scope() as db:
        return export_service.purge(db, object_storage.get_storage())
