"""Plan limits are enforced in the service layer (HTTP 402), and a downgrade
never removes data — it only stops adding more."""
from datetime import UTC, datetime, timedelta

from app.models import Invitation, Membership, Role, User, Vendor
from app.services import entitlements, integration_service

API = "/api/v1"


def _org(api, email):
    client, _ = api.register(email)
    return client, client.get(f"{API}/orgs").json()[0]["id"]


def _add_vendors_directly(api, oid, n, start=0):
    with api.db() as db:
        for i in range(start, start + n):
            db.add(Vendor(org_id=oid, name=f"Vendor {i:03d}", is_mapped=False))
        db.commit()


def _vendors(api, oid):
    with api.db() as db:
        return db.query(Vendor).filter_by(org_id=oid).count()


# --------------------------------------------------------------------------- #
# Vendors                                                                      #
# --------------------------------------------------------------------------- #
def test_free_plan_caps_vendors_and_upgrading_lifts_it(api):
    client, oid = _org(api, "cap@acme.io")
    _add_vendors_directly(api, oid, 10)
    res = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Eleventh"})
    assert res.status_code == 402
    assert "Free plan includes 10 vendors" in res.json()["detail"]
    assert "Upgrade to Team" in res.json()["detail"]

    api.set_plan(oid, "team")
    assert client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Eleventh"}).status_code == 201


def test_duplicate_name_is_still_a_conflict_at_the_cap(api):
    client, oid = _org(api, "dup@acme.io")
    _add_vendors_directly(api, oid, 10)
    res = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Vendor 000"})
    assert res.status_code == 409  # the more specific problem wins


def test_sbom_import_is_all_or_nothing_against_the_cap(api):
    client, oid = _org(api, "sbomcap@acme.io")
    _add_vendors_directly(api, oid, 8)
    items = [{"name": f"pkg-{i}"} for i in range(5)] + [{"name": "Vendor 000"}]  # 1 exists
    res = client.post(f"{API}/orgs/{oid}/sbom/import", json={"items": items})
    assert res.status_code == 402
    assert "add 5 vendors" in res.json()["detail"] and "room for 2 more" in res.json()["detail"]
    assert _vendors(api, oid) == 8  # nothing partially imported

    ok = client.post(f"{API}/orgs/{oid}/sbom/import", json={"items": items[:2]})
    assert ok.status_code == 200 and ok.json()["created"] == 2


# --------------------------------------------------------------------------- #
# Seats                                                                        #
# --------------------------------------------------------------------------- #
def test_invitations_count_toward_seats(api):
    client, oid = _org(api, "seats@acme.io")  # owner = seat 1
    for email in ("a@acme.io", "b@acme.io"):  # seats 2 and 3 (pending)
        res = client.post(f"{API}/orgs/{oid}/invitations", json={"email": email, "role": "member"})
        assert res.status_code == 201
    res = client.post(f"{API}/orgs/{oid}/invitations", json={"email": "c@acme.io", "role": "member"})
    assert res.status_code == 402
    assert "3 seats" in res.json()["detail"] and "Upgrade to Team" in res.json()["detail"]


def test_expired_invitations_free_their_seat(api):
    client, oid = _org(api, "exp-seat@acme.io")
    with api.db() as db:
        for i in range(2):
            db.add(Invitation(org_id=oid, email=f"old{i}@acme.io", role=Role.member,
                              token=f"tok-{i}", invited_by=None,
                              expires_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()
    res = client.post(f"{API}/orgs/{oid}/invitations", json={"email": "new@acme.io", "role": "member"})
    assert res.status_code == 201


def test_accepting_needs_a_free_seat(api):
    owner, oid = _org(api, "acc@acme.io")
    api.set_plan(oid, "team")
    invite = owner.post(f"{API}/orgs/{oid}/invitations",
                        json={"email": "late@acme.io", "role": "member"}).json()
    with api.db() as db:  # fill the Free plan's 3 seats, then downgrade
        for i in range(2):
            user = User(email=f"m{i}@acme.io", password_hash=None)
            db.add(user)
            db.flush()
            db.add(Membership(org_id=oid, user_id=user.id, role=Role.member))
        db.commit()
        token = db.get(Invitation, invite["id"]).token
    api.set_plan(oid, "free")

    late, _ = api.register("late@acme.io")
    res = late.post(f"{API}/invitations/accept", json={"token": token})
    assert res.status_code == 402
    assert "Ask an owner to upgrade" in res.json()["detail"]
    api.set_plan(oid, "team")
    assert late.post(f"{API}/invitations/accept", json={"token": token}).status_code == 200


def test_business_seats_are_unlimited(api):
    client, oid = _org(api, "biz@acme.io")
    api.set_plan(oid, "business")
    for i in range(12):
        res = client.post(f"{API}/orgs/{oid}/invitations",
                          json={"email": f"p{i}@acme.io", "role": "viewer"})
        assert res.status_code == 201


# --------------------------------------------------------------------------- #
# Sync interval                                                                #
# --------------------------------------------------------------------------- #
def test_sync_interval_floor_on_save_and_at_scheduling(api):
    client, oid = _org(api, "sync@acme.io")
    url = f"{API}/orgs/{oid}/integration"
    assert client.get(url).json()["min_sync_hours"] == 24
    res = client.put(url, json={"sync_cadence_hours": 6})
    assert res.status_code == 402 and "every 24 hours" in res.json()["detail"]

    api.set_plan(oid, "team")
    assert client.put(url, json={"sync_cadence_hours": 6}).json()["sync_cadence_hours"] == 6
    with api.db() as db:
        assert integration_service.cadence_hours(db, oid) == 6

    # Downgrade: the stored choice is kept, but scheduling uses the plan floor.
    api.set_plan(oid, "free")
    assert client.get(url).json() == {"nvd_key_set": False, "nvd_key_verified_at": None,
                                      "sync_cadence_hours": 6, "min_sync_hours": 24}
    with api.db() as db:
        assert integration_service.cadence_hours(db, oid) == 24


# --------------------------------------------------------------------------- #
# PDF reports + downgrades                                                     #
# --------------------------------------------------------------------------- #
def test_pdf_reports_need_a_paid_plan(api):
    client, oid = _org(api, "pdf@acme.io")
    res = client.post(f"{API}/orgs/{oid}/exports", json={"format": "pdf"})
    assert res.status_code == 402 and "PDF reports" in res.json()["detail"]


def test_downgrade_keeps_every_vendor(api):
    client, oid = _org(api, "down@acme.io")
    api.set_plan(oid, "team")
    _add_vendors_directly(api, oid, 20)
    api.set_plan(oid, "free")

    assert len(client.get(f"{API}/orgs/{oid}/vendors").json()) == 20  # all still visible
    res = client.post(f"{API}/orgs/{oid}/vendors", json={"name": "One more"})
    assert res.status_code == 402 and "has 20" in res.json()["detail"]


def test_unknown_plan_value_is_treated_as_free(api):
    client, oid = _org(api, "odd@acme.io")
    api.set_plan(oid, "platinum")
    with api.db() as db:
        from app.models import Organization

        assert entitlements.plan_for(db.get(Organization, oid)).id == "free"


def test_plan_catalog_is_ordered_and_consistent():
    plans = [entitlements.PLANS[p] for p in entitlements.PLAN_ORDER]
    assert [p.price_cents for p in plans] == [0, 4999, 19999]
    assert [entitlements.format_price(p) for p in plans] == ["$0", "$49.99", "$199.99"]
    assert [p.min_sync_hours for p in plans] == [24, 6, 1]
    assert entitlements.PLANS["business"].max_members is None
