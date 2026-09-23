"""Per-org integration settings: write-only NVD key, cadence, RBAC."""
from app.services import integration_service

API = "/api/v1"


def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def test_defaults_when_unconfigured(api):
    client, _ = api.register("int@acme.io")
    oid = _org_id(client)
    body = client.get(f"{API}/orgs/{oid}/integration").json()
    assert body == {"nvd_key_set": False, "sync_cadence_hours": 24}


def test_set_key_and_cadence_key_is_write_only(api):
    client, _ = api.register("int2@acme.io")
    oid = _org_id(client)
    resp = client.put(
        f"{API}/orgs/{oid}/integration",
        json={"nvd_api_key": "secret-key-abc", "sync_cadence_hours": 6},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["nvd_key_set"] is True and body["sync_cadence_hours"] == 6
    assert "nvd_api_key" not in body  # never echoed back

    # Stored encrypted, decryptable to the original plaintext.
    with api.db() as db:
        assert integration_service.resolve_nvd_api_key(db, oid) == "secret-key-abc"


def test_clearing_key_with_empty_string(api):
    client, _ = api.register("int3@acme.io")
    oid = _org_id(client)
    client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "k"})
    assert client.get(f"{API}/orgs/{oid}/integration").json()["nvd_key_set"] is True

    client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": ""})
    assert client.get(f"{API}/orgs/{oid}/integration").json()["nvd_key_set"] is False


def test_cadence_only_update_leaves_key(api):
    client, _ = api.register("int4@acme.io")
    oid = _org_id(client)
    client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "keep-me"})
    client.put(f"{API}/orgs/{oid}/integration", json={"sync_cadence_hours": 12})
    body = client.get(f"{API}/orgs/{oid}/integration").json()
    assert body["nvd_key_set"] is True and body["sync_cadence_hours"] == 12


def test_cadence_bounds_rejected(api):
    client, _ = api.register("int5@acme.io")
    oid = _org_id(client)
    assert client.put(f"{API}/orgs/{oid}/integration", json={"sync_cadence_hours": 0}).status_code == 422
    assert client.put(f"{API}/orgs/{oid}/integration", json={"sync_cadence_hours": 999}).status_code == 422


def test_viewer_cannot_edit_but_can_read(api):
    owner, _ = api.register("int-owner@acme.io")
    oid = _org_id(owner)
    viewer, _ = api.register("int-view@acme.io")
    token = owner.post(
        f"{API}/orgs/{oid}/invitations", json={"email": "int-view@acme.io", "role": "viewer"}
    ).json()["token"]
    viewer.post(f"{API}/invitations/accept", json={"token": token})

    assert viewer.get(f"{API}/orgs/{oid}/integration").status_code == 200
    assert viewer.put(f"{API}/orgs/{oid}/integration", json={"sync_cadence_hours": 8}).status_code == 403


def test_non_member_gets_404(api):
    owner, _ = api.register("int-o2@acme.io")
    oid = _org_id(owner)
    outsider, _ = api.register("int-out@acme.io")
    assert outsider.get(f"{API}/orgs/{oid}/integration").status_code == 404
