"""Dashboard aggregation endpoint tests (offline, via synced fixtures)."""
from datetime import date, timedelta

from app.api import vendors as vendors_api
from seed.pipeline import FIXTURES_DIR, _offline_fetch

API = "/api/v1"


def _org(client) -> dict:
    return client.get(f"{API}/orgs").json()[0]


def _offline(api):
    api.app.dependency_overrides[vendors_api.get_vendor_fetcher] = lambda: _offline_fetch(
        FIXTURES_DIR
    )


def _add_and_sync(client, org_id, name, cpe, **fields) -> int:
    vid = client.post(
        f"{API}/orgs/{org_id}/vendors",
        json={"name": name, "cpe_prefix": cpe, **fields},
    ).json()["id"]
    client.post(f"{API}/orgs/{org_id}/vendors/{vid}/sync")
    return vid


def test_summary_reflects_synced_vendor(api):
    _offline(api)
    client, _ = api.register("dash@example.com")
    org = _org(client)
    _add_and_sync(client, org["id"], "Fortinet", "cpe:2.3:a:fortinet", data_sensitivity="regulated")

    summary = client.get(f"{API}/orgs/{org['id']}/dashboard/summary").json()
    assert summary["vendor_count"] == 1
    assert summary["mapped_count"] == 1
    assert summary["kev_exposed_vendors"] >= 1
    assert sum(summary["tier_distribution"].values()) == 1


def test_heatmap_has_16_cells_and_places_vendor(api):
    _offline(api)
    client, _ = api.register("hm@example.com")
    org = _org(client)
    _add_and_sync(client, org["id"], "Fortinet", "cpe:2.3:a:fortinet", data_sensitivity="regulated")

    cells = client.get(f"{API}/orgs/{org['id']}/dashboard/heatmap").json()["cells"]
    assert len(cells) == 16
    assert sum(c["count"] for c in cells) == 1
    assert any("Fortinet" in c["vendors"] for c in cells)


def test_top_risk_orders_and_excludes_unassessed(api):
    _offline(api)
    client, _ = api.register("tr@example.com")
    org = _org(client)
    _add_and_sync(client, org["id"], "Fortinet", "cpe:2.3:a:fortinet", data_sensitivity="regulated")
    client.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "Unsynced"})  # Not Assessed

    top = client.get(f"{API}/orgs/{org['id']}/dashboard/top-risk").json()
    assert top[0]["vendor_name"] == "Fortinet"
    assert top[0]["tier"] != "Not Assessed"


def test_watchlist_includes_near_renewal_excludes_far(api):
    _offline(api)
    client, _ = api.register("wl@example.com")
    org = _org(client)
    near = (date.today() + timedelta(days=30)).isoformat()
    far = (date.today() + timedelta(days=200)).isoformat()
    _add_and_sync(
        client, org["id"], "Fortinet", "cpe:2.3:a:fortinet",
        data_sensitivity="regulated", contract_renewal_date=near,
    )
    _add_and_sync(
        client, org["id"], "Cisco", "cpe:2.3:a:cisco",
        data_sensitivity="regulated", contract_renewal_date=far,
    )

    watch = client.get(f"{API}/orgs/{org['id']}/dashboard/watchlist").json()
    names = [w["vendor_name"] for w in watch]
    assert "Fortinet" in names          # High/Critical + renews in 30 days
    assert "Cisco" not in names          # renews in 200 days -> out of window
