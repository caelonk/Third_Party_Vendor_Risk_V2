"""Risk-trend endpoint tests. Snapshots are inserted directly with controlled
timestamps to exercise the multi-day aggregation."""
from datetime import UTC, datetime, timedelta

from app.models import RiskSnapshot

API = "/api/v1"


def _org(client) -> dict:
    return client.get(f"{API}/orgs").json()[0]


def _make_vendor(client, org_id, name="Acme") -> int:
    return client.post(f"{API}/orgs/{org_id}/vendors", json={"name": name}).json()["id"]


def _snapshot(vendor_id, days_ago, *, tier, cves, kev=0, cvss=None):
    return RiskSnapshot(
        vendor_id=vendor_id,
        tier=tier,
        threat_band="T3",
        exposure_band="E2",
        max_cvss=cvss,
        cve_count=cves,
        kev_count=kev,
        captured_at=datetime.now(UTC) - timedelta(days=days_ago),
    )


def test_vendor_trend_is_ordered_history(api):
    client, _ = api.register("t1@acme.io")
    org = _org(client)
    vid = _make_vendor(client, org["id"])
    with api.db() as db:
        db.add_all([
            _snapshot(vid, 4, tier="Medium", cves=3, cvss=7.5),
            _snapshot(vid, 2, tier="High", cves=6, cvss=8.8),
            _snapshot(vid, 0, tier="Critical", cves=9, kev=2, cvss=9.8),
        ])
        db.commit()

    trend = client.get(f"{API}/orgs/{org['id']}/vendors/{vid}/trend").json()
    assert [p["tier"] for p in trend] == ["Medium", "High", "Critical"]
    assert [p["cve_count"] for p in trend] == [3, 6, 9]
    assert trend[-1]["kev_count"] == 2


def test_portfolio_trend_aggregates_latest_per_vendor_per_day(api):
    client, _ = api.register("t2@acme.io")
    org = _org(client)
    v1 = _make_vendor(client, org["id"], "One")
    v2 = _make_vendor(client, org["id"], "Two")
    with api.db() as db:
        db.add_all([
            _snapshot(v1, 3, tier="High", cves=5, kev=1),
            _snapshot(v2, 3, tier="Low", cves=2),
            _snapshot(v1, 0, tier="Critical", cves=8, kev=3),  # v1 grew
        ])
        db.commit()

    series = client.get(f"{API}/orgs/{org['id']}/snapshots").json()
    assert len(series) == 2  # two distinct snapshot days
    # Day 1: v1=5, v2=2 -> 7 total, 1 KEV vendor.
    assert series[0]["total_cves"] == 7
    assert series[0]["kev_vendors"] == 1
    # Day 2: latest v1=8 + carried-forward v2=2 -> 10 total, 1 KEV vendor.
    assert series[1]["total_cves"] == 10
    assert series[1]["kev_vendors"] == 1
    assert series[1]["tier_distribution"]["Critical"] == 1


def test_vendor_trend_foreign_vendor_404(api):
    c1, _ = api.register("t3@acme.io")
    org1 = _org(c1)
    vid = _make_vendor(c1, org1["id"])
    c2, _ = api.register("t4@acme.io")
    org2 = _org(c2)
    assert c2.get(f"{API}/orgs/{org2['id']}/vendors/{vid}/trend").status_code == 404
