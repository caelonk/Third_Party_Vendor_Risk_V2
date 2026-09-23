"""Background tasks.

* ``ping`` — health check, keeps the worker wiring exercisable.
* ``dispatch_due_syncs`` — Beat fires this on a cron; it selects due vendors,
  dedupes them to CPE prefixes, and fans out one ``sync_prefix`` task per prefix.
* ``sync_prefix`` — incrementally syncs one prefix from NVD (rate-limited across
  workers by a Redis token bucket) and finalizes each of its due vendors.

The real work lives in :mod:`app.services.scheduled_sync_service`; these tasks
are the thin Celery/Redis/session shell around it.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..db import session_scope
from ..services import scheduled_sync_service as sched
from ..services.scheduled_sync_service import PrefixWork
from .celery_app import celery_app
from .rate_limit import RedisRateLimiter

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="app.workers.tasks.dispatch_due_syncs")
def dispatch_due_syncs() -> dict:
    """Beat entrypoint: enqueue one ``sync_prefix`` task per due CPE prefix."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    dispatched = 0
    with session_scope() as db:
        for work in sched.plan_due_work(db, now):
            # JSON transport: send org groups as [org_id, [vendor_ids]] pairs.
            groups = [[org_id, ids] for org_id, ids in work.vendors_by_org.items()]
            sync_prefix.delay(work.prefix, groups)
            dispatched += 1
    log.info("dispatch_due_syncs: enqueued %d prefix task(s)", dispatched)
    return {"prefixes_dispatched": dispatched}


@celery_app.task(
    name="app.workers.tasks.sync_prefix",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def sync_prefix(self, prefix: str, groups: list) -> dict:
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
    )
    limiter = RedisRateLimiter(client, max_wait=settings.nvd_rate_max_wait_seconds)
    fetch_prefix = sched.build_live_fetch_prefix(limiter)

    try:
        with session_scope() as db:
            result = sched.sync_prefix(db, work, fetch_prefix=fetch_prefix)
    except Exception as exc:  # transient NVD/Redis/DB failure — let Celery retry
        log.warning("sync_prefix(%s) failed: %s; retrying", prefix, exc)
        raise self.retry(exc=exc) from exc
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 — lock may have already expired
            pass

    log.info(
        "sync_prefix(%s): fetched=%s synced=%d failed=%d",
        prefix, result.fetched, result.vendors_synced, result.vendors_failed,
    )
    return {
        "prefix": result.prefix,
        "fetched": result.fetched,
        "vendors_synced": result.vendors_synced,
        "vendors_failed": result.vendors_failed,
        "error": result.error,
    }
