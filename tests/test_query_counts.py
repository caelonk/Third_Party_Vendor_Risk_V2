"""Guard against N+1 queries: list, dashboard, and export endpoints must run the
same number of SQL statements whether an org has 3 vendors or 15.

Counts statements with a SQLAlchemy engine event, so a regression that
re-introduces a per-vendor query fails here instead of in production.
"""
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.models import (
    AlertChannel,
    AlertRule,
    AlertType,
    ExportFormat,
    Organization,
    Vendor,
    VendorVulnerability,
    Vulnerability,
)
from app.services import alerts_service, export_service

API = "/api/v1"


@contextmanager
def count_queries(api):
    with api.db() as db:
        engine = db.get_bind()
    counter = {"n": 0}

    def _before(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _seed(api, oid: int, start: int, n: int, *, cvss: float = 7.5, kev_every: int = 2,
          renewal: date | None = None) -> None:
    with api.db() as db:
        for i in range(start, start + n):
            v = Vendor(org_id=oid, name=f"Vendor {i:03d}", cpe_prefix=f"cpe:2.3:a:v{i}:p",
                       is_mapped=True, contract_renewal_date=renewal)
            db.add(v)
            db.flush()
            for j in range(2):  # two CVEs each, so grouping is exercised
                cid = f"CVE-2026-{i:03d}{j}"
                db.add(Vulnerability(cve_id=cid, cvss_score=cvss, is_kev=bool(kev_every and i % kev_every == 0)))
                db.flush()
                db.add(VendorVulnerability(vendor_id=v.id, cve_id=cid))
        db.commit()


@pytest.mark.parametrize(
    "path",
    [
        "/vendors",
        "/dashboard/summary",
        "/dashboard/heatmap",
        "/dashboard/watchlist",
        "/dashboard/top-risk",
    ],
)
def test_query_count_is_constant_in_vendor_count(api, path):
    client, _ = api.register("qc@acme.io")
    oid = client.get(f"{API}/orgs").json()[0]["id"]
    url = f"{API}/orgs/{oid}{path}"

    _seed(api, oid, 0, 3)
    assert client.get(url).status_code == 200  # warm-up
    with count_queries(api) as small:
        client.get(url)

    _seed(api, oid, 3, 12)
    with count_queries(api) as large:
        assert client.get(url).status_code == 200

    assert large["n"] == small["n"], f"{path}: {small['n']} queries at 3 vendors, {large['n']} at 15"


def test_renewal_evaluation_query_count_is_constant(api):
    client, _ = api.register("qc2@acme.io")
    oid = client.get(f"{API}/orgs").json()[0]["id"]
    ref = date(2026, 1, 1)
    with api.db() as db:
        db.add(AlertRule(org_id=oid, type=AlertType.renewal_due, channel=AlertChannel.email,
                         config={"days": 90}))
        db.commit()

    # Low-severity vendors inside the window: assessed, but never alerted — so
    # any growth in queries would come from assessment alone.
    _seed(api, oid, 0, 3, cvss=3.1, kev_every=0, renewal=ref + timedelta(days=10))
    with count_queries(api) as small, api.db() as db:
        alerts_service.evaluate_renewals(db, oid, reference=ref)
    _seed(api, oid, 3, 12, cvss=3.1, kev_every=0, renewal=ref + timedelta(days=10))
    with count_queries(api) as large, api.db() as db:
        assert alerts_service.evaluate_renewals(db, oid, reference=ref) == []

    assert large["n"] == small["n"]


def test_export_render_query_count_is_constant(api):
    client, _ = api.register("qc3@acme.io")
    oid = client.get(f"{API}/orgs").json()[0]["id"]

    def render() -> None:
        with api.db() as db:
            org = db.get(Organization, oid)
            export_service.render(db, org, ExportFormat.csv)

    _seed(api, oid, 0, 3)
    render()  # warm-up
    with count_queries(api) as small:
        render()
    _seed(api, oid, 3, 12)
    with count_queries(api) as large:
        render()

    assert large["n"] == small["n"], f"{small['n']} queries at 3 vendors, {large['n']} at 15"
