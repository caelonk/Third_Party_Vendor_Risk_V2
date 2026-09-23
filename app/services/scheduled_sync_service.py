"""Scheduled auto-sync: the logic Celery Beat drives on a cadence.

Flow (see [[project-status]] Phase 2C):

1. **Due selection** — vendors whose ``next_sync_at`` has elapsed (or was never
   set), that are mapped to a CPE prefix.
2. **Prefix dedup** — CVE data is public and identical for every tenant, so a
   prefix shared by many vendors (even across orgs) is fetched from NVD **once**.
3. **Incremental fetch** — keyed on ``cpe_sync_state.last_mod_watermark`` so only
   CVEs modified since the last run are pulled (new CVEs *and* CVSS/KEV changes).
   The first pull for a prefix has no watermark and does a publication-window
   backfill. A global Redis token bucket enforces NVD's per-key rate limit.
4. **Per-vendor finalize** — each due vendor is linked to the refreshed cache, a
   risk snapshot is appended, alert rules are evaluated, and its next sync is
   scheduled. The shared ``core.sync.ingest`` orchestration enforces the
   honest-data rules (a failed fetch never downgrades prior-good data).

The network + rate-limit layer is injected as a port (:data:`FetchPrefixFn`) so
the due-selection, dedup, watermark, and scheduling logic are all unit-testable
offline; the live path is verified end-to-end against Redis/Postgres in Docker.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core import nvd_client
from core import sync as core_sync
from core.nvd_client import QUERY_TYPES, NVDConfig, VendorFetchError

from ..config import get_settings
from ..models import CpeSyncState, SyncRun, SyncStatus, Vendor
from ..workers.rate_limit import BucketSpec, bucket_id
from . import alerts_service, integration_service, sync_service
from .store import SqlAlchemyVulnStore

# A port that fetches one CPE prefix from NVD and returns one payload per query
# kind, keyed ``{"recent": {...}, "kev": {...}}``; raises VendorFetchError on
# failure. Signature: fetch_prefix(prefix, *, last_mod_start, api_key).
FetchPrefixFn = Callable[..., dict[str, dict]]

_noop = lambda *a, **k: None  # noqa: E731 — silence core.sync's logging


@dataclass
class PrefixWork:
    """One CPE prefix's due vendors, grouped by org (the fetch is shared)."""

    prefix: str
    vendors_by_org: dict[int, list[int]] = field(default_factory=dict)


@dataclass
class PrefixResult:
    prefix: str
    fetched: bool = False
    vendors_synced: int = 0
    vendors_failed: int = 0
    error: str | None = None


# --------------------------------------------------------------------------- #
# Due selection + prefix dedup (pure DB queries — unit-tested on SQLite)       #
# --------------------------------------------------------------------------- #
def select_due_vendors(db: Session, now: datetime) -> list[Vendor]:
    """Mapped vendors whose scheduled sync is due (or never scheduled)."""
    stmt = (
        select(Vendor)
        .where(
            Vendor.is_mapped.is_(True),
            Vendor.cpe_prefix.is_not(None),
            or_(Vendor.next_sync_at.is_(None), Vendor.next_sync_at <= now),
        )
        .order_by(Vendor.id)
    )
    return list(db.scalars(stmt).all())


def plan_due_work(db: Session, now: datetime) -> list[PrefixWork]:
    """Group the due vendors by CPE prefix so each prefix is fetched once."""
    by_prefix: dict[str, PrefixWork] = {}
    for v in select_due_vendors(db, now):
        assert v.cpe_prefix is not None  # guaranteed by the query filter
        work = by_prefix.setdefault(v.cpe_prefix, PrefixWork(prefix=v.cpe_prefix))
        work.vendors_by_org.setdefault(v.org_id, []).append(v.id)
    return list(by_prefix.values())


# --------------------------------------------------------------------------- #
# Watermark + key resolution                                                  #
# --------------------------------------------------------------------------- #
def get_or_create_state(db: Session, prefix: str) -> CpeSyncState:
    state = db.scalar(select(CpeSyncState).where(CpeSyncState.cpe_prefix == prefix))
    if state is None:
        state = CpeSyncState(cpe_prefix=prefix)
        db.add(state)
        db.flush()
    return state


def _resolve_api_key(db: Session, work: PrefixWork) -> str | None:
    """A usable NVD key for this prefix: any subscribing org's key, else system.

    The cache is global and the data identical for every tenant, so any valid key
    may fetch a given prefix. Prefer an org-provided key to spread rate limits.
    """
    for org_id in work.vendors_by_org:
        key = integration_service.resolve_nvd_api_key(db, org_id)
        if key:
            return key
    return get_settings().nvd_api_key


# --------------------------------------------------------------------------- #
# Default (live) fetch port — rate-limited NVD calls                          #
# --------------------------------------------------------------------------- #
def _spec_for(api_key: str | None) -> BucketSpec:
    s = get_settings()
    per_window = (
        s.nvd_rate_with_key_per_window if api_key else s.nvd_rate_keyless_per_window
    )
    return BucketSpec.from_window(per_window, s.nvd_rate_window_seconds)


def build_live_fetch_prefix(limiter=None, *, now: datetime | None = None) -> FetchPrefixFn:
    """A fetch_prefix that pulls live from NVD, one paced/rate-limited call per query."""
    now = now or datetime.now(UTC)

    def fetch_prefix(prefix: str, *, last_mod_start: datetime | None, api_key: str | None):
        config = NVDConfig(api_key=api_key)
        session = nvd_client.make_session(config)
        spec = _spec_for(api_key)
        bucket = bucket_id(api_key)
        out: dict[str, dict] = {}
        for qt in QUERY_TYPES:
            if limiter is not None:
                limiter.acquire(spec, bucket)
            out[qt] = nvd_client.fetch_query(
                prefix,
                qt,
                config=config,
                session=session,
                now=now,
                last_mod_start=last_mod_start if qt == "recent" else None,
                log=_noop,
            )
        return out

    return fetch_prefix


class _MemoFetch:
    """Adapts a one-shot ``fetch_prefix`` to core.sync.ingest's ``fetch(vendor, qt)``.

    ingest calls ``fetch`` once per (vendor, query_type); every due vendor here
    shares one prefix, so the network runs exactly once and the payload (or the
    failure) is replayed to each vendor.
    """

    def __init__(self, prefix, last_mod, fetch_prefix, api_key) -> None:
        self._prefix = prefix
        self._last_mod = last_mod
        self._fetch_prefix = fetch_prefix
        self._api_key = api_key
        self._payloads: dict[str, dict] | None = None
        self._error: VendorFetchError | None = None
        self._done = False

    @property
    def ok(self) -> bool:
        return self._done and self._error is None

    @property
    def error(self) -> VendorFetchError | None:
        return self._error

    def __call__(self, vendor: dict, query_type: str) -> dict:
        if not self._done:
            self._done = True
            try:
                self._payloads = self._fetch_prefix(
                    self._prefix, last_mod_start=self._last_mod, api_key=self._api_key
                )
            except VendorFetchError as exc:
                self._error = exc
        if self._error is not None:
            raise self._error
        assert self._payloads is not None
        return self._payloads[query_type]


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #
def sync_prefix(
    db: Session,
    work: PrefixWork,
    *,
    fetch_prefix: FetchPrefixFn,
    now: datetime | None = None,
) -> PrefixResult:
    """Incrementally sync one CPE prefix and finalize each of its due vendors."""
    now = now or datetime.now(UTC)
    state = get_or_create_state(db, work.prefix)
    last_mod = state.last_mod_watermark
    api_key = _resolve_api_key(db, work)
    result = PrefixResult(prefix=work.prefix)

    memo = _MemoFetch(work.prefix, last_mod, fetch_prefix, api_key)

    for org_id, vendor_ids in work.vendors_by_org.items():
        vendors = [v for vid in vendor_ids if (v := db.get(Vendor, vid)) is not None]
        if not vendors:
            continue
        prev_snapshots = {v.id: sync_service.latest_snapshot(db, v.id) for v in vendors}

        run = SyncRun(org_id=org_id, mode="scheduled", status=SyncStatus.running)
        db.add(run)
        db.flush()

        store = SqlAlchemyVulnStore(db, org_id)
        prepared: list[dict] = [
            {
                "vendor_name": v.name,
                "cpe_prefix": v.cpe_prefix,
                "business": {},
                "match_method": v.match_method.value if v.match_method else "virtual_match",
            }
            for v in vendors
        ]
        ingest = core_sync.ingest(store, prepared, fetch=memo, log=_noop)

        for v in vendors:
            v.last_synced_at = now
            sync_service.schedule_next_sync(db, org_id, v, now=now)
            if memo.ok:
                snapshot = sync_service.build_snapshot(db, v, now=now)
                db.commit()
                alerts_service.evaluate_on_sync(
                    db, org_id, v, prev_snapshots[v.id], snapshot
                )
                result.vendors_synced += 1
            else:
                db.commit()
                result.vendors_failed += 1

        run.status = SyncStatus(ingest.status)
        run.completed_at = now
        run.vendors_attempted = ingest.attempted
        run.vendors_succeeded = ingest.succeeded
        run.cves_upserted = ingest.cves_upserted
        run.error_detail = "; ".join(ingest.errors) or None
        db.commit()

    # Advance the watermark only on a clean fetch, so a failure re-pulls the same
    # window next time instead of skipping changes it never saw.
    result.fetched = memo.ok
    if memo.ok:
        if last_mod is None:
            state.last_full_backfill_at = now
        state.last_mod_watermark = now
        state.subscriber_count = _subscriber_count(db, work.prefix)
    else:
        result.error = str(memo.error) if memo.error else "fetch failed"
    db.commit()
    return result


def _subscriber_count(db: Session, prefix: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Vendor).where(Vendor.cpe_prefix == prefix))
        or 0
    )


def run_due_syncs(
    db: Session,
    *,
    fetch_prefix: FetchPrefixFn | None = None,
    limiter=None,
    now: datetime | None = None,
) -> list[PrefixResult]:
    """Sync every due prefix inline. Beat's dispatcher fans these out per prefix."""
    now = now or datetime.now(UTC)
    fetch_prefix = fetch_prefix or build_live_fetch_prefix(limiter, now=now)
    return [sync_prefix(db, work, fetch_prefix=fetch_prefix, now=now) for work in plan_due_work(db, now)]
