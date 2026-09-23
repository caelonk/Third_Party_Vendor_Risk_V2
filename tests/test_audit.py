"""Audit log: mutations are recorded with actor + target, surfaced admin-only,
and secrets never land in the audit payload."""
import json

API = "/api/v1"


def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def test_vendor_actions_are_recorded_newest_first(api):
    client, _ = api.register("aud@acme.io")
    oid = _org_id(client)
    vid = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Acme"}).json()["id"]
    client.patch(f"{API}/orgs/{oid}/vendors/{vid}", json={"business_criticality": "high"})

    log = client.get(f"{API}/orgs/{oid}/audit-log").json()
    actions = [e["action"] for e in log]
    assert "vendor.created" in actions and "vendor.updated" in actions
    assert log[0]["action"] == "vendor.updated"  # newest first

    created = next(e for e in log if e["action"] == "vendor.created")
    assert created["actor_email"] == "aud@acme.io"
    assert created["target_type"] == "vendor" and created["target_id"] == str(vid)
    assert created["extra"]["name"] == "Acme"


def test_integration_update_is_audited_without_the_key_value(api):
    client, _ = api.register("aud2@acme.io")
    oid = _org_id(client)
    client.put(
        f"{API}/orgs/{oid}/integration",
        json={"nvd_api_key": "super-secret-key", "sync_cadence_hours": 6},
    )
    log = client.get(f"{API}/orgs/{oid}/audit-log").json()
    entry = next(e for e in log if e["action"] == "integration.updated")
    assert set(entry["extra"]["fields"]) == {"nvd_api_key", "sync_cadence_hours"}
    # The secret must never appear anywhere in the audit payload.
    assert "super-secret-key" not in json.dumps(log)


def test_member_actions_are_audited(api):
    owner, _ = api.register("aud-owner@acme.io")
    oid = _org_id(owner)
    token = owner.post(
        f"{API}/orgs/{oid}/invitations", json={"email": "aud-m@acme.io", "role": "member"}
    ).json()["token"]
    member, _ = api.register("aud-m@acme.io")
    member.post(f"{API}/invitations/accept", json={"token": token})

    log = owner.get(f"{API}/orgs/{oid}/audit-log").json()
    assert any(e["action"] == "member.invited" for e in log)


def test_audit_log_is_admin_only(api):
    owner, _ = api.register("aud-o2@acme.io")
    oid = _org_id(owner)
    token = owner.post(
        f"{API}/orgs/{oid}/invitations", json={"email": "aud-v@acme.io", "role": "viewer"}
    ).json()["token"]
    viewer, _ = api.register("aud-v@acme.io")
    viewer.post(f"{API}/invitations/accept", json={"token": token})

    assert viewer.get(f"{API}/orgs/{oid}/audit-log").status_code == 403


def test_audit_log_non_member_404(api):
    owner, _ = api.register("aud-o3@acme.io")
    oid = _org_id(owner)
    outsider, _ = api.register("aud-out@acme.io")
    assert outsider.get(f"{API}/orgs/{oid}/audit-log").status_code == 404
