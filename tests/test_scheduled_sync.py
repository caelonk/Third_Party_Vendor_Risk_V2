"""Scheduled auto-sync: due selection, prefix dedup, watermark, integrity.

The network + rate-limit layer is injected as a fake ``fetch_prefix``, so these
exercise the due-selection, dedup, watermark, snapshot, and scheduling logic
offline. The live NVD/Redis path is verified end-to-end in Docker.
"""
from datetime import datetime, timedelta

import pytest

from app.models import (
    AlertChannel,
    AlertRule,
    AlertType,
    CpeSyncState,
    RiskSnapshot,
    SyncRun,
    Vendor,
)
from app.services import integration_service
from app.services import scheduled_sync_service as sched
from core.nvd_client import VendorFetchError

API = "/api/v1"
PREFIX = "cpe:2.3:a:acme:widget"


def _cve(cid, *, score=9.8, kev=False):
    cve = {
        "cve": {
            "id": cid,
            "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": score, "baseSeverity": "CRITICAL"}}]},
        }
    }
    if kev:
        cve["cve"]["cisaExploitAdd"] = "2024-01-01"
    return cve


def _payloads(*cves):
    return {
        "recent": {"vulnerabilities": list(cves)},
        "kev": {"vulnerabilities": [c for c in cves if c["cve"].get("cisaExploitAdd")]},
    }


class FakeFetch:
    """Records how it was called; returns fixed payloads or raises."""

    def __init__(self, payloads=None, error=None):
        self.calls = []
        self._payloads = payloads if payloads is not None else _payloads()
        self._error = error

    def __call__(self, prefix, *, last_mod_start, api_key):
        self.calls.append({"prefix": prefix, "last_mod_start": last_mod_start, "api_key": api_key})
        if self._error is not None:
            raise self._error
        return self._payloads


def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def _mk_vendor(db, oid, name, *, prefix=PREFIX, mapped=True, next_sync_at=None):
    v = Vendor(org_id=oid, name=name, cpe_prefix=prefix, is_mapped=mapped, next_sync_at=next_sync_at)
    db.add(v)
    db.commit()
    return v.id


# --------------------------------------------------------------------------- #
# Due selection + prefix dedup                                                #
# --------------------------------------------------------------------------- #
def test_select_due_excludes_unprefixed_and_future(api):
    client, _ = api.register("due@acme.io")
    oid = _org_id(client)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        due_never = _mk_vendor(db, oid, "DueNever", next_sync_at=None)
        due_past = _mk_vendor(db, oid, "DuePast", next_sync_at=now - timedelta(hours=1))
        _future = _mk_vendor(db, oid, "Future", next_sync_at=now + timedelta(hours=1))
        _noprefix = _mk_vendor(db, oid, "NoPrefix", prefix=None)

        due_ids = {v.id for v in sched.select_due_vendors(db, now)}
        assert due_ids == {due_never, due_past}


def test_never_synced_vendor_with_a_prefix_is_due(api):
    """A vendor added with a CPE prefix (form or SBOM import) is not yet mapped —
    it must still be picked up by scheduled sync, not wait for a manual click.
    Likewise a vendor whose first fetch failed must be retried."""
    client, _ = api.register("due2@acme.io")
    oid = _org_id(client)
    now = datetime(2026, 1, 1)
    with api.db() as db:
        fresh = _mk_vendor(db, oid, "Fresh Import", mapped=False)  # has PREFIX, never synced
        due_ids = {v.id for v in sched.select_due_vendors(db, now)}
        assert fresh in due_ids


def test_plan_dedupes_shared_prefix_and_groups_by_org(api):
    a, _ = api.register("planA@acme.io")
    b, _ = api.register("planB@beta.io")
    oa, ob = _org_id(a), _org_id(b)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        va1 = _mk_vendor(db, oa, "A1")
        va2 = _mk_vendor(db, oa, "A2")           # same prefix as A1
        vb1 = _mk_vendor(db, ob, "B1")           # same prefix, different org
        work = sched.plan_due_work(db, now)
        assert len(work) == 1                    # one prefix
        w = work[0]
        assert w.prefix == PREFIX
        assert set(w.vendors_by_org[oa]) == {va1, va2}
        assert set(w.vendors_by_org[ob]) == {vb1}


# --------------------------------------------------------------------------- #
# sync_prefix: success path                                                   #
# --------------------------------------------------------------------------- #
def test_sync_prefix_success_links_snapshots_and_advances_watermark(api):
    client, _ = api.register("ok@acme.io")
    oid = _org_id(client)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        vid = _mk_vendor(db, oid, "Acme")
        work = sched.plan_due_work(db, now)[0]
        fetch = FakeFetch(_payloads(_cve("CVE-2024-1", kev=True), _cve("CVE-2024-2")))

        result = sched.sync_prefix(db, work, fetch_prefix=fetch, now=now)

        assert result.fetched and result.vendors_synced == 1 and result.vendors_failed == 0
        # First run: no watermark passed to NVD (publication-window backfill).
        assert fetch.calls[0]["last_mod_start"] is None

        v = db.get(Vendor, vid)
        assert v.is_mapped is True
        assert v.last_synced_at == now
        assert v.next_sync_at == now + timedelta(hours=24)  # default cadence

        snap = db.query(RiskSnapshot).filter_by(vendor_id=vid).one()
        assert snap.kev_count == 1 and snap.cve_count == 2

        state = db.query(CpeSyncState).filter_by(cpe_prefix=PREFIX).one()
        assert state.last_mod_watermark == now
        assert state.last_full_backfill_at == now
        assert state.subscriber_count == 1

        run = db.query(SyncRun).filter_by(org_id=oid, mode="scheduled").one()
        assert run.status.value == "success" and run.vendors_succeeded == 1


def test_second_run_is_incremental_from_watermark(api):
    client, _ = api.register("inc@acme.io")
    oid = _org_id(client)
    t1 = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        _mk_vendor(db, oid, "Acme")
        work = sched.plan_due_work(db, t1)[0]
        sched.sync_prefix(db, work, fetch_prefix=FakeFetch(_payloads(_cve("CVE-1"))), now=t1)

        # A later run should pass the stored watermark as last_mod_start.
        t2 = t1 + timedelta(days=2)
        work2 = sched.plan_due_work(db, t2)[0]
        fetch2 = FakeFetch(_payloads(_cve("CVE-1")))
        sched.sync_prefix(db, work2, fetch_prefix=fetch2, now=t2)
        assert fetch2.calls[0]["last_mod_start"] == t1


def test_shared_prefix_across_orgs_fetches_once(api):
    a, _ = api.register("shA@acme.io")
    b, _ = api.register("shB@beta.io")
    oa, ob = _org_id(a), _org_id(b)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        _mk_vendor(db, oa, "A1")
        _mk_vendor(db, ob, "B1")
        work = sched.plan_due_work(db, now)[0]
        fetch = FakeFetch(_payloads(_cve("CVE-1")))
        result = sched.sync_prefix(db, work, fetch_prefix=fetch, now=now)
        assert len(fetch.calls) == 1          # one network fetch for both orgs
        assert result.vendors_synced == 2     # both vendors finalized


# --------------------------------------------------------------------------- #
# sync_prefix: failure path (honest-data integrity)                           #
# --------------------------------------------------------------------------- #
def test_fetch_failure_keeps_prior_good_and_does_not_advance_watermark(api):
    client, _ = api.register("fail@acme.io")
    oid = _org_id(client)
    t1 = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        vid = _mk_vendor(db, oid, "Acme")
        # First, a good run so there is prior-good data + a watermark.
        work = sched.plan_due_work(db, t1)[0]
        sched.sync_prefix(db, work, fetch_prefix=FakeFetch(_payloads(_cve("CVE-1"))), now=t1)
        snaps_before = db.query(RiskSnapshot).filter_by(vendor_id=vid).count()

        # Now a failing run.
        t2 = t1 + timedelta(days=2)
        work2 = sched.plan_due_work(db, t2)[0]
        result = sched.sync_prefix(
            db, work2, fetch_prefix=FakeFetch(error=VendorFetchError("boom")), now=t2
        )
        assert not result.fetched and result.vendors_failed == 1

        v = db.get(Vendor, vid)
        assert v.is_mapped is True                       # not downgraded
        assert v.next_sync_at == t2 + timedelta(hours=24)  # still rescheduled

        # No new snapshot on failure.
        assert db.query(RiskSnapshot).filter_by(vendor_id=vid).count() == snaps_before

        # Watermark stays at t1 so the missed window is re-pulled next time.
        state = db.query(CpeSyncState).filter_by(cpe_prefix=PREFIX).one()
        assert state.last_mod_watermark == t1

        run = db.query(SyncRun).filter_by(org_id=oid, mode="scheduled").order_by(SyncRun.id.desc()).first()
        assert run.status.value == "failed"


# --------------------------------------------------------------------------- #
# Alerts fire from scheduled sync                                             #
# --------------------------------------------------------------------------- #
def test_scheduled_sync_emits_new_kev_alert(api):
    client, _ = api.register("alert@acme.io")
    oid = _org_id(client)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        vid = _mk_vendor(db, oid, "Acme")
        db.add(AlertRule(org_id=oid, type=AlertType.new_kev, channel=AlertChannel.email, config={}))
        # Prior snapshot with no KEV so the new KEV is a genuine change.
        db.add(RiskSnapshot(vendor_id=vid, tier="Medium", cve_count=1, kev_count=0, captured_at=now - timedelta(days=1)))
        db.commit()
        work = sched.plan_due_work(db, now)[0]
        sched.sync_prefix(db, work, fetch_prefix=FakeFetch(_payloads(_cve("CVE-1", kev=True))), now=now)

    feed = client.get(f"{API}/orgs/{oid}/notifications").json()
    assert any(n["type"] == "new_kev" for n in feed)


# --------------------------------------------------------------------------- #
# Per-org key resolution                                                      #
# --------------------------------------------------------------------------- #
def test_resolve_prefers_org_key_then_falls_back(api):
    client, _ = api.register("key@acme.io")
    oid = _org_id(client)
    now = datetime(2026, 1, 1)  # naive: SQLite drops tzinfo; prod (Postgres) is tz-aware
    with api.db() as db:
        _mk_vendor(db, oid, "Acme")
        work = sched.plan_due_work(db, now)[0]
        # No org key -> system key (None in tests).
        fetch = FakeFetch(_payloads(_cve("CVE-1")))
        sched.sync_prefix(db, work, fetch_prefix=fetch, now=now)
        assert fetch.calls[0]["api_key"] is None

        # Configure an org key; the next run should use it.
        integration_service.update_integration(db, oid, nvd_api_key="org-secret-123")
        t2 = now + timedelta(days=2)
        work2 = sched.plan_due_work(db, t2)[0]
        fetch2 = FakeFetch(_payloads(_cve("CVE-1")))
        sched.sync_prefix(db, work2, fetch_prefix=fetch2, now=t2)
        assert fetch2.calls[0]["api_key"] == "org-secret-123"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))


# --------------------------------------------------------------------------- #
# Backfill vs incremental routing                                             #
# --------------------------------------------------------------------------- #
def test_never_synced_prefix_is_a_backfill_then_becomes_incremental(api):
    client, _ = api.register("bf@acme.io")
    oid = _org_id(client)
    t1 = datetime(2026, 1, 1)
    with api.db() as db:
        _mk_vendor(db, oid, "Acme")
        work = sched.plan_due_work(db, t1)[0]
        assert work.backfill is True  # no watermark yet: first, expensive pull
        sched.sync_prefix(db, work, fetch_prefix=FakeFetch(_payloads(_cve("CVE-1"))), now=t1)

        again = sched.plan_due_work(db, t1 + timedelta(days=2))[0]
        assert again.backfill is False  # watermark set: cheap incremental pull


def test_a_failed_backfill_stays_a_backfill(api):
    client, _ = api.register("bf2@acme.io")
    oid = _org_id(client)
    t1 = datetime(2026, 1, 1)
    with api.db() as db:
        _mk_vendor(db, oid, "Acme")
        work = sched.plan_due_work(db, t1)[0]
        sched.sync_prefix(db, work, fetch_prefix=FakeFetch(error=VendorFetchError("x")), now=t1)
        assert sched.plan_due_work(db, t1 + timedelta(days=2))[0].backfill is True


def test_dispatcher_routes_backfills_and_incrementals_to_separate_queues(api, monkeypatch):
    from contextlib import contextmanager

    from app.workers import tasks

    client, _ = api.register("route@acme.io")
    oid = _org_id(client)
    with api.db() as db:
        _mk_vendor(db, oid, "Old", prefix="cpe:2.3:a:old:old")
        _mk_vendor(db, oid, "New", prefix="cpe:2.3:a:new:new")
        db.add(CpeSyncState(cpe_prefix="cpe:2.3:a:old:old", last_mod_watermark=datetime(2025, 1, 1)))
        db.commit()

    @contextmanager
    def test_session():
        with api.db() as db:
            yield db

    sent = []
    monkeypatch.setattr(tasks, "session_scope", test_session)
    monkeypatch.setattr(
        tasks.sync_prefix, "apply_async",
        lambda args, kwargs, queue: sent.append((args[0], kwargs["backfill"], queue)),
    )
    result = tasks.dispatch_due_syncs.run()
    assert sorted(sent) == [
        ("cpe:2.3:a:new:new", True, "backfill"),
        ("cpe:2.3:a:old:old", False, "sync"),
    ]
    assert result == {"prefixes_dispatched": 2, "sync": 1, "backfill": 1}
