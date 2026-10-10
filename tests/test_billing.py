"""Billing: signed, idempotent, order-safe webhooks; owner-only checkout and
portal; the full subscription lifecycle through the development stand-in; and
the Stripe adapter against a fake client (no network)."""
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe

from app.api.billing import get_billing_provider
from app.config import Settings
from app.models import AuditLog, BillingEvent, Membership, Organization, Role, User, Vendor
from app.services.billing import (
    DevBilling,
    SignatureError,
    StripeBilling,
    build_billing,
    sign_payload,
    verify_signature,
)
from app.services.exceptions import UnavailableError

API = "/api/v1"
BASE = "http://testserver"


@pytest.fixture
def dev(api):
    provider = DevBilling(base_url=BASE, secret="test-secret")
    api.app.dependency_overrides[get_billing_provider] = lambda: provider
    return provider


def _owner(api, email="own@acme.io"):
    client, _ = api.register(email, org_name="Acme")
    return client, client.get(f"{API}/orgs").json()[0]["id"]


def _post_event(api, dev, event, *, secret=None, timestamp=None, header=None):
    payload = json.dumps(event).encode()
    sig = header if header is not None else sign_payload(
        payload, secret or dev.webhook_secret, timestamp=timestamp
    )
    return api.client().post(
        f"{API}/billing/webhook", content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )


def _sub_event(dev, oid, *, etype="customer.subscription.updated", plan="team",
               status="active", sub_id="sub_1", customer="cus_1", created=None, metadata=True):
    sub = dev.subscription(subscription_id=sub_id, customer_id=customer, org_id=oid, plan=plan,
                           status=status, period_end=int(time.time()) + 86400)
    if not metadata:
        sub["metadata"] = {}
    return dev.event(etype, sub, created=created)


def _plan(api, oid):
    with api.db() as db:
        return db.get(Organization, oid).plan


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --------------------------------------------------------------------------- #
# Webhook authenticity, idempotency, ordering                                  #
# --------------------------------------------------------------------------- #
def test_webhook_rejects_bad_missing_and_stale_signatures(api, dev):
    _, oid = _owner(api)
    event = _sub_event(dev, oid)
    assert _post_event(api, dev, event, secret="whsec_wrong").status_code == 400
    assert _post_event(api, dev, event, header="").status_code == 400
    old = int(time.time()) - 3600  # a captured request replayed an hour later
    assert _post_event(api, dev, event, timestamp=old).status_code == 400
    assert _plan(api, oid) == "free"

    ok = _post_event(api, dev, event)
    assert ok.status_code == 200 and ok.json()["outcome"] == "applied"
    assert _plan(api, oid) == "team"


def test_webhook_is_404_when_billing_is_off(api):
    res = api.client().post(f"{API}/billing/webhook", content=b"{}")
    assert res.status_code == 404


def test_malformed_signed_payload_is_400(api, dev):
    payload = b"not json"
    res = api.client().post(f"{API}/billing/webhook", content=payload,
                            headers={"Stripe-Signature": sign_payload(payload, dev.webhook_secret)})
    assert res.status_code == 400


def test_redelivered_event_is_applied_once(api, dev):
    _, oid = _owner(api)
    event = _sub_event(dev, oid)
    assert _post_event(api, dev, event).json()["outcome"] == "applied"
    assert _post_event(api, dev, event).json()["outcome"] == "duplicate"
    with api.db() as db:
        assert db.query(BillingEvent).filter_by(event_id=event["id"]).count() == 1
        changes = db.query(AuditLog).filter_by(org_id=oid, action="billing.plan_changed").all()
        assert len(changes) == 1 and changes[0].actor_user_id is None
        assert changes[0].extra == {"from": "free", "to": "team", "status": "active"}


def test_an_older_event_arriving_late_is_ignored(api, dev):
    _, oid = _owner(api)
    now = int(time.time())
    _post_event(api, dev, _sub_event(dev, oid, status="active", created=now - 20))
    deleted = _sub_event(dev, oid, etype="customer.subscription.deleted", status="canceled",
                         created=now)
    assert _post_event(api, dev, deleted).json()["outcome"] == "applied"
    assert _plan(api, oid) == "free"
    late = _sub_event(dev, oid, status="active", created=now - 10)  # sent before the cancel
    assert _post_event(api, dev, late).json()["outcome"] == "stale"
    assert _plan(api, oid) == "free"


def test_an_old_subscription_ending_cannot_cancel_the_new_one(api, dev):
    _, oid = _owner(api)
    now = int(time.time())
    _post_event(api, dev, _sub_event(dev, oid, sub_id="sub_new", plan="business", created=now - 5))
    old_end = _sub_event(dev, oid, etype="customer.subscription.deleted", sub_id="sub_old",
                         status="canceled", created=now)
    assert _post_event(api, dev, old_end).json()["outcome"] == "stale"
    assert _plan(api, oid) == "business"


@pytest.mark.parametrize(
    ("status", "plan"),
    [("active", "team"), ("trialing", "team"), ("past_due", "team"),
     ("unpaid", "free"), ("canceled", "free"), ("incomplete", "free")],
)
def test_status_decides_whether_the_paid_plan_applies(api, dev, status, plan):
    _, oid = _owner(api)
    _post_event(api, dev, _sub_event(dev, oid, status=status))
    assert _plan(api, oid) == plan


def test_price_maps_to_plan_and_unknown_prices_are_ignored(api, dev):
    _, oid = _owner(api)
    event = _sub_event(dev, oid, plan="business", metadata=True)
    _post_event(api, dev, event)
    assert _plan(api, oid) == "business"

    mystery = _sub_event(dev, oid, metadata=False, customer="cus_zzz")
    mystery["data"]["object"]["items"]["data"][0]["price"]["id"] = "price_unknown"
    mystery["data"]["object"]["metadata"] = {"org_id": str(oid)}
    assert _post_event(api, dev, mystery).json()["outcome"] == "ignored"
    assert _plan(api, oid) == "business"


def test_checkout_links_the_customer_for_later_events(api, dev):
    _, oid = _owner(api)
    _post_event(api, dev, dev.event("checkout.session.completed", {
        "object": "checkout.session", "client_reference_id": str(oid),
        "customer": "cus_linked", "subscription": "sub_1", "metadata": {},
    }))
    # A later event carrying only the customer id still finds the org.
    res = _post_event(api, dev, _sub_event(dev, oid, customer="cus_linked", metadata=False))
    assert res.json()["outcome"] == "applied"
    assert _plan(api, oid) == "team"


def test_unmatched_and_unhandled_events_are_acknowledged(api, dev):
    orphan = _sub_event(dev, 999_999, metadata=False, customer="cus_nobody")
    assert _post_event(api, dev, orphan).json()["outcome"] == "unmatched"
    other = dev.event("charge.refunded", {"object": "charge"})
    assert _post_event(api, dev, other).json()["outcome"] == "ignored"


def test_failed_payment_is_audited(api, dev):
    _, oid = _owner(api)
    _post_event(api, dev, dev.event("invoice.payment_failed", {
        "object": "invoice", "customer": "cus_1", "attempt_count": 2,
        "parent": {"subscription_details": {"metadata": {"org_id": str(oid)}}},
    }))
    with api.db() as db:
        entry = db.query(AuditLog).filter_by(org_id=oid, action="billing.payment_failed").one()
        assert entry.extra == {"attempt": 2}


# --------------------------------------------------------------------------- #
# Summary + owner actions                                                      #
# --------------------------------------------------------------------------- #
def test_summary_shows_plan_usage_and_catalog(api, dev):
    client, oid = _owner(api)
    with api.db() as db:
        db.add(Vendor(org_id=oid, name="One", is_mapped=False))
        db.commit()
    client.post(f"{API}/orgs/{oid}/invitations", json={"email": "p@acme.io", "role": "viewer"})
    body = client.get(f"{API}/orgs/{oid}/billing").json()
    assert body["plan"]["id"] == "free" and body["status"] is None
    assert body["vendors"] == {"used": 1, "limit": 10}
    assert body["members"] == {"used": 2, "limit": 3} and body["members_pending"] == 1
    assert body["provider"] == "dev_stand_in"
    assert [p["id"] for p in body["plans"]] == ["free", "team", "business"]
    assert body["plans"][2]["max_members"] is None


def test_only_the_owner_can_start_checkout_or_open_the_portal(api, dev):
    owner, oid = _owner(api)
    admin, _ = api.register("adm@acme.io")
    with api.db() as db:
        uid = db.query(User).filter_by(email="adm@acme.io").one().id
        db.add(Membership(org_id=oid, user_id=uid, role=Role.admin))
        db.commit()
    assert admin.get(f"{API}/orgs/{oid}/billing").status_code == 200  # can see it
    assert admin.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"}).status_code == 403
    assert admin.post(f"{API}/orgs/{oid}/billing/portal").status_code == 403
    outsider, _ = api.register("out@else.io")
    assert outsider.get(f"{API}/orgs/{oid}/billing").status_code == 404
    assert outsider.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"}).status_code == 404

    res = owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"})
    assert res.status_code == 200 and res.json()["url"].startswith(f"{BASE}/api/v1/billing/dev/checkout?")
    assert owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "free"}).status_code == 422
    # No billing account yet, so there's no portal to open.
    assert owner.post(f"{API}/orgs/{oid}/billing/portal").status_code == 409


def test_billing_actions_503_when_billing_is_off(api):
    owner, oid = _owner(api)
    assert owner.get(f"{API}/orgs/{oid}/billing").json()["provider"] is None
    assert owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"}).status_code == 503


# --------------------------------------------------------------------------- #
# The whole lifecycle through the development stand-in                         #
# --------------------------------------------------------------------------- #
def _checkout(owner, oid, plan="team", action="pay"):
    url = owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": plan}).json()["url"]
    page = owner.get(url)
    assert page.status_code == 200 and "Development stand-in" in page.text
    token = _query(url)["token"]
    return owner.get(f"{API}/billing/dev/checkout/complete",
                     params={"token": token, "action": action}, follow_redirects=False)


def _portal(owner, oid, action):
    url = owner.post(f"{API}/orgs/{oid}/billing/portal").json()["url"]
    token = _query(url)["token"]
    res = owner.get(f"{API}/billing/dev/portal/action", params={"token": token, "action": action},
                    follow_redirects=False)
    assert res.status_code == 303
    page = owner.get(res.headers["location"])
    assert page.status_code == 200
    return owner.get(f"{API}/orgs/{oid}/billing").json()


def test_full_lifecycle_through_the_stand_in(api, dev):
    owner, oid = _owner(api)
    with api.db() as db:
        for i in range(8):
            db.add(Vendor(org_id=oid, name=f"V{i}", is_mapped=False))
        db.commit()

    done = _checkout(owner, oid, "team")
    assert done.status_code == 302 and done.headers["location"].endswith("/settings?billing=success#billing")
    body = owner.get(f"{API}/orgs/{oid}/billing").json()
    assert body["plan"]["id"] == "team" and body["status"] == "active"
    assert body["has_subscription"] and body["has_billing_account"] and body["current_period_end"]
    # A second checkout while subscribed is refused (use the portal instead).
    assert owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "business"}).status_code == 409

    body = _portal(owner, oid, "fail_payment")
    assert body["status"] == "past_due" and body["plan"]["id"] == "team"  # still entitled
    body = _portal(owner, oid, "recover_payment")
    assert body["status"] == "active"
    body = _portal(owner, oid, "switch_business")
    assert body["plan"]["id"] == "business"
    body = _portal(owner, oid, "cancel_at_period_end")
    assert body["cancel_at_period_end"] is True and body["plan"]["id"] == "business"
    body = _portal(owner, oid, "resume")
    assert body["cancel_at_period_end"] is False
    body = _portal(owner, oid, "cancel_now")
    assert body["plan"]["id"] == "free" and body["status"] == "canceled"
    assert not body["has_subscription"]
    assert body["vendors"]["used"] == 8  # nothing removed on the way down

    with api.db() as db:
        actions = [a.action for a in db.query(AuditLog).filter_by(org_id=oid).order_by(AuditLog.id)]
    assert actions.count("billing.plan_changed") == 3  # free->team, team->business, ->free
    assert "billing.payment_failed" in actions and "billing.checkout_started" in actions

    # Subscribing again reuses the same customer.
    assert _checkout(owner, oid, "team").status_code == 302
    assert owner.get(f"{API}/orgs/{oid}/billing").json()["plan"]["id"] == "team"


def test_cancelling_at_checkout_changes_nothing(api, dev):
    owner, oid = _owner(api)
    res = _checkout(owner, oid, action="cancel")
    assert res.headers["location"].endswith("/settings?billing=cancelled#billing")
    assert _plan(api, oid) == "free"


def test_paying_twice_does_not_open_a_second_subscription(api, dev):
    owner, oid = _owner(api)
    url = owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"}).json()["url"]
    token = _query(url)["token"]
    for _ in range(2):
        owner.get(f"{API}/billing/dev/checkout/complete", params={"token": token, "action": "pay"},
                  follow_redirects=False)
    with api.db() as db:
        created = db.query(BillingEvent).filter_by(type="customer.subscription.created").count()
    assert created == 1


def test_stand_in_pages_reject_bad_tokens_and_are_off_for_stripe(api, dev):
    client = api.client()
    assert client.get(f"{API}/billing/dev/checkout", params={"token": "nope"}).status_code == 400
    api.app.dependency_overrides[get_billing_provider] = lambda: StripeBilling(
        secret_key="sk_test_x", webhook_secret="whsec_x", price_team="price_t",
        price_business="price_b", client=object(),
    )
    assert client.get(f"{API}/billing/dev/checkout", params={"token": "x"}).status_code == 404


def test_switching_provider_ignores_the_other_providers_ids(api, dev):
    """A stand-in customer id must never be sent to real Stripe (and vice versa)."""
    owner, oid = _owner(api)
    assert _checkout(owner, oid, "team").status_code == 302  # stand-in subscription
    assert owner.get(f"{API}/orgs/{oid}/billing").json()["has_subscription"] is True

    fake = _FakeStripe()
    api.app.dependency_overrides[get_billing_provider] = lambda: _stripe(fake)
    body = owner.get(f"{API}/orgs/{oid}/billing").json()
    assert body["provider"] == "stripe_test"
    assert body["has_subscription"] is False and body["has_billing_account"] is False
    assert body["status"] is None
    # No portal for a customer Stripe has never heard of...
    assert owner.post(f"{API}/orgs/{oid}/billing/portal").status_code == 409
    # ...and checkout starts a fresh customer instead of sending "cus_dev_...".
    assert owner.post(f"{API}/orgs/{oid}/billing/checkout", json={"plan": "team"}).status_code == 200
    assert "customer" not in fake.calls[0] and fake.calls[0]["customer_email"] == "own@acme.io"


# --------------------------------------------------------------------------- #
# Stripe adapter (fake client, no network)                                     #
# --------------------------------------------------------------------------- #
class _FakeSessions:
    def __init__(self, calls, url, fail=False):
        self.calls, self.url, self.fail = calls, url, fail

    def create(self, params=None, options=None):
        self.calls.append(params)
        if self.fail:
            raise stripe.APIConnectionError("network down")
        return type("Session", (), {"url": self.url})()


class _FakeStripe:
    def __init__(self, fail=False):
        self.calls: list[dict] = []
        checkout = type("C", (), {"sessions": _FakeSessions(self.calls, "https://checkout.stripe.test/c", fail)})
        portal = type("P", (), {"sessions": _FakeSessions(self.calls, "https://billing.stripe.test/p", fail)})
        self.v1 = type("V1", (), {"checkout": checkout, "billing_portal": portal})


def _stripe(fake, **kw):
    return StripeBilling(secret_key="sk_test_123", webhook_secret="whsec_abc",
                         price_team="price_team_1", price_business="price_biz_1", client=fake, **kw)


def test_stripe_checkout_and_portal_parameters():
    fake = _FakeStripe()
    s = _stripe(fake)
    url = s.create_checkout(org_id=7, plan="team", customer_id=None, email="o@acme.io",
                            success_url="https://app/s", cancel_url="https://app/c")
    assert url == "https://checkout.stripe.test/c"
    params = fake.calls[0]
    assert params["mode"] == "subscription"
    assert params["line_items"] == [{"price": "price_team_1", "quantity": 1}]
    assert params["client_reference_id"] == "7"
    assert params["subscription_data"]["metadata"] == {"org_id": "7", "plan": "team"}
    assert params["customer_email"] == "o@acme.io" and "customer" not in params

    s.create_checkout(org_id=7, plan="business", customer_id="cus_9", email="o@acme.io",
                      success_url="s", cancel_url="c")
    assert fake.calls[1]["customer"] == "cus_9" and "customer_email" not in fake.calls[1]
    assert s.create_portal(org_id=7, customer_id="cus_9", return_url="r") == "https://billing.stripe.test/p"
    assert fake.calls[2] == {"customer": "cus_9", "return_url": "r"}
    # A specific portal configuration is passed through when one is set.
    configured = _stripe(fake, portal_configuration="bpc_123")
    configured.create_portal(org_id=7, customer_id="cus_9", return_url="r")
    assert fake.calls[3] == {"customer": "cus_9", "return_url": "r", "configuration": "bpc_123"}
    assert s.plan_for_price("price_biz_1") == "business" and s.plan_for_price("x") is None


def test_stripe_errors_become_a_polite_503():
    with pytest.raises(UnavailableError):
        _stripe(_FakeStripe(fail=True)).create_checkout(
            org_id=1, plan="team", customer_id=None, email=None, success_url="s", cancel_url="c")
    no_price = StripeBilling(secret_key="sk_test_1", webhook_secret="w", price_team=None,
                             price_business=None, client=_FakeStripe())
    with pytest.raises(UnavailableError):
        no_price.create_checkout(org_id=1, plan="team", customer_id=None, email=None,
                                 success_url="s", cancel_url="c")


def test_our_signatures_verify_with_stripes_own_verifier():
    payload = b'{"id":"evt_1","type":"x"}'
    header = sign_payload(payload, "whsec_abc")
    stripe.WebhookSignature.verify_header(payload, header, "whsec_abc", tolerance=300)
    verify_signature(payload, header, "whsec_abc")
    with pytest.raises(SignatureError):
        verify_signature(payload + b" ", header, "whsec_abc")  # tampered body
    with pytest.raises(SignatureError):
        verify_signature(payload, header, "")  # no secret configured -> reject


def test_provider_selection_is_test_mode_by_design():
    base = {"stripe_webhook_secret": "whsec_x", "billing_dev_provider": False}
    assert build_billing(Settings(stripe_secret_key=None, **base)) is None
    assert build_billing(Settings(stripe_secret_key="sk_test_1", **base)).kind == "stripe_test"
    # A live key is refused unless explicitly allowed.
    assert build_billing(Settings(stripe_secret_key="sk_live_1", **base)) is None
    assert build_billing(Settings(stripe_secret_key="rk_live_1", **base)) is None
    allowed = build_billing(Settings(stripe_secret_key="sk_live_1", stripe_allow_live=True, **base))
    assert allowed is not None and allowed.kind == "stripe_live"
    # The stand-in: only when enabled, never in production, and real keys win.
    dev = {"stripe_secret_key": None, "billing_dev_provider": True}
    assert isinstance(build_billing(Settings(**dev)), DevBilling)
    assert build_billing(Settings(env="production", **dev)) is None
    assert isinstance(build_billing(Settings(stripe_secret_key="sk_test_1", billing_dev_provider=True)),
                      StripeBilling)
