"""Alert rule CRUD/RBAC, sync-time evaluation, and the notification feed."""
from app.models import (
    AlertChannel,
    AlertRule,
    AlertType,
    Notification,
    NotificationStatus,
    RiskSnapshot,
    Vendor,
)
from app.services import alerts_service

API = "/api/v1"


def _org(client) -> dict:
    return client.get(f"{API}/orgs").json()[0]


def test_alert_rule_crud(api):
    client, _ = api.register("ar-owner@acme.io")
    org = _org(client)
    base = f"{API}/orgs/{org['id']}/alert-rules"

    created = client.post(base, json={"type": "new_kev", "channel": "email"})
    assert created.status_code == 201
    rid = created.json()["id"]
    assert created.json()["is_active"] is True

    assert len(client.get(base).json()) == 1

    upd = client.patch(f"{base}/{rid}", json={"is_active": False})
    assert upd.json()["is_active"] is False

    assert client.request("DELETE", f"{base}/{rid}").status_code == 204
    assert client.get(base).json() == []


def test_viewer_cannot_create_rule(api):
    owner, _ = api.register("ar-boss@acme.io")
    org = _org(owner)
    viewer, _ = api.register("ar-view@acme.io")
    token = owner.post(
        f"{API}/orgs/{org['id']}/invitations",
        json={"email": "ar-view@acme.io", "role": "viewer"},
    ).json()["token"]
    viewer.post(f"{API}/invitations/accept", json={"token": token})

    resp = viewer.post(f"{API}/orgs/{org['id']}/alert-rules", json={"type": "new_kev"})
    assert resp.status_code == 403


def test_evaluate_on_sync_emits_and_dedups(api):
    client, _ = api.register("ev@acme.io")
    org = _org(client)
    oid = org["id"]
    vid = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Acme"}).json()["id"]

    with api.db() as db:
        db.add_all([
            AlertRule(org_id=oid, type=AlertType.new_kev, channel=AlertChannel.email, config={}),
            AlertRule(org_id=oid, type=AlertType.tier_change, channel=AlertChannel.email, config={}),
        ])
        db.commit()
        vendor = db.get(Vendor, vid)
        prev = RiskSnapshot(vendor_id=vid, tier="Medium", cve_count=3, kev_count=0)
        new = RiskSnapshot(vendor_id=vid, tier="Critical", cve_count=9, kev_count=2)
        emitted = alerts_service.evaluate_on_sync(db, oid, vendor, prev, new)
        assert {n.type for n in emitted} == {AlertType.new_kev, AlertType.tier_change}
        # Same day, same deltas -> deduplicated, nothing new.
        assert alerts_service.evaluate_on_sync(db, oid, vendor, prev, new) == []

    feed = client.get(f"{API}/orgs/{oid}/notifications").json()
    assert len(feed) == 2
    assert client.get(f"{API}/orgs/{oid}/notifications/unread-count").json()["unread"] == 2


def test_no_alert_without_matching_rule(api):
    client, _ = api.register("nr@acme.io")
    org = _org(client)
    oid = org["id"]
    vid = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Beta"}).json()["id"]
    with api.db() as db:
        vendor = db.get(Vendor, vid)
        prev = RiskSnapshot(vendor_id=vid, tier="Low", cve_count=1, kev_count=0)
        new = RiskSnapshot(vendor_id=vid, tier="Critical", cve_count=9, kev_count=5)
        # No alert rules configured -> no notifications.
        assert alerts_service.evaluate_on_sync(db, oid, vendor, prev, new) == []
    assert client.get(f"{API}/orgs/{oid}/notifications").json() == []


def test_notification_read_flow(api):
    client, _ = api.register("rd@acme.io")
    org = _org(client)
    oid = org["id"]
    with api.db() as db:
        db.add_all([
            Notification(org_id=oid, type=AlertType.new_kev, dedup_key=f"{oid}:k1",
                         title="One", status=NotificationStatus.pending),
            Notification(org_id=oid, type=AlertType.tier_change, dedup_key=f"{oid}:k2",
                         title="Two", status=NotificationStatus.pending),
        ])
        db.commit()

    assert client.get(f"{API}/orgs/{oid}/notifications/unread-count").json()["unread"] == 2
    nid = client.get(f"{API}/orgs/{oid}/notifications").json()[0]["id"]
    client.post(f"{API}/orgs/{oid}/notifications/{nid}/read")
    assert client.get(f"{API}/orgs/{oid}/notifications/unread-count").json()["unread"] == 1
    assert client.post(f"{API}/orgs/{oid}/notifications/read-all").json()["unread"] == 0
    assert client.get(f"{API}/orgs/{oid}/notifications/unread-count").json()["unread"] == 0
