"""Vendor CRUD, RBAC, cross-org isolation, and offline on-demand sync."""
from app.api import vendors as vendors_api
from seed.pipeline import FIXTURES_DIR, _offline_fetch

API = "/api/v1"


def _personal_org(client) -> dict:
    return client.get(f"{API}/orgs").json()[0]


def _use_offline_sync(api):
    """Point the sync endpoint at the saved NVD fixtures instead of the network."""
    api.app.dependency_overrides[vendors_api.get_vendor_fetcher] = lambda: _offline_fetch(
        FIXTURES_DIR
    )


def test_create_list_get_vendor(api):
    client, _ = api.register("v-owner@example.com")
    org = _personal_org(client)
    created = client.post(
        f"{API}/orgs/{org['id']}/vendors",
        json={"name": "Acme Corp", "annual_contract_value": 120000, "data_sensitivity": "confidential"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_mapped"] is False
    assert body["assessment"]["tier"] == "Not Assessed"  # not synced yet

    listed = client.get(f"{API}/orgs/{org['id']}/vendors").json()
    assert [v["name"] for v in listed] == ["Acme Corp"]

    got = client.get(f"{API}/orgs/{org['id']}/vendors/{body['id']}")
    assert got.status_code == 200


def test_update_and_delete_vendor(api):
    client, _ = api.register("v2@example.com")
    org = _personal_org(client)
    vid = client.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "Beta"}).json()["id"]

    upd = client.patch(
        f"{API}/orgs/{org['id']}/vendors/{vid}", json={"annual_contract_value": 500000}
    )
    assert upd.json()["annual_contract_value"] == 500000

    assert client.request("DELETE", f"{API}/orgs/{org['id']}/vendors/{vid}").status_code == 204
    assert client.get(f"{API}/orgs/{org['id']}/vendors/{vid}").status_code == 404


def test_duplicate_vendor_name_conflicts(api):
    client, _ = api.register("v3@example.com")
    org = _personal_org(client)
    client.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "Dup"})
    again = client.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "Dup"})
    assert again.status_code == 409


def test_cross_org_isolation(api):
    c1, _ = api.register("iso1@example.com")
    org1 = _personal_org(c1)
    vid = c1.post(f"{API}/orgs/{org1['id']}/vendors", json={"name": "Secret"}).json()["id"]

    c2, _ = api.register("iso2@example.com")
    org2 = _personal_org(c2)
    # c2 is not a member of org1 -> 404; and the vendor id is not in org2 -> 404.
    assert c2.get(f"{API}/orgs/{org1['id']}/vendors/{vid}").status_code == 404
    assert c2.get(f"{API}/orgs/{org2['id']}/vendors/{vid}").status_code == 404


def test_viewer_cannot_write(api):
    owner, _ = api.register("vo@example.com")
    org = _personal_org(owner)
    viewer, _ = api.register("viewer@example.com")
    token = owner.post(
        f"{API}/orgs/{org['id']}/invitations",
        json={"email": "viewer@example.com", "role": "viewer"},
    ).json()["token"]
    viewer.post(f"{API}/invitations/accept", json={"token": token})

    # Viewer can read but not create.
    assert viewer.get(f"{API}/orgs/{org['id']}/vendors").status_code == 200
    assert viewer.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "X"}).status_code == 403


def test_sync_vendor_offline(api):
    _use_offline_sync(api)
    client, _ = api.register("sync@example.com")
    org = _personal_org(client)
    vid = client.post(
        f"{API}/orgs/{org['id']}/vendors",
        json={"name": "Fortinet", "cpe_prefix": "cpe:2.3:a:fortinet", "data_sensitivity": "confidential"},
    ).json()["id"]

    run = client.post(f"{API}/orgs/{org['id']}/vendors/{vid}/sync")
    assert run.status_code == 200
    assert run.json()["status"] == "success"
    assert run.json()["cves_upserted"] > 0

    vendor = client.get(f"{API}/orgs/{org['id']}/vendors/{vid}").json()
    assert vendor["is_mapped"] is True
    assert vendor["match_method"] == "virtual_match"
    assert vendor["assessment"]["cve_count"] > 0
    assert vendor["assessment"]["tier"] != "Not Assessed"


def test_resync_is_idempotent(api):
    _use_offline_sync(api)
    client, _ = api.register("resync@example.com")
    org = _personal_org(client)
    vid = client.post(
        f"{API}/orgs/{org['id']}/vendors",
        json={"name": "Fortinet", "cpe_prefix": "cpe:2.3:a:fortinet"},
    ).json()["id"]

    first = client.post(f"{API}/orgs/{org['id']}/vendors/{vid}/sync").json()
    count1 = client.get(f"{API}/orgs/{org['id']}/vendors/{vid}").json()["assessment"]["cve_count"]
    second = client.post(f"{API}/orgs/{org['id']}/vendors/{vid}/sync").json()
    count2 = client.get(f"{API}/orgs/{org['id']}/vendors/{vid}").json()["assessment"]["cve_count"]

    assert first["status"] == second["status"] == "success"
    assert count1 == count2 and count1 > 0  # re-sync adds no duplicate links


def test_sync_without_cpe_prefix_is_rejected(api):
    _use_offline_sync(api)
    client, _ = api.register("nocpe@example.com")
    org = _personal_org(client)
    vid = client.post(f"{API}/orgs/{org['id']}/vendors", json={"name": "Unmapped"}).json()["id"]
    resp = client.post(f"{API}/orgs/{org['id']}/vendors/{vid}/sync")
    assert resp.status_code == 422  # no CPE mapping
