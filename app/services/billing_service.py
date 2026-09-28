"""Subscriptions: apply the provider's webhook events, and start checkout/portal.

The provider (Stripe or its stand-in) is the source of truth. We learn about
changes only through signed webhook events and apply them defensively:

* **Authentic** — the signature is checked before anything is parsed.
* **Idempotent** — each event id is recorded once (``billing_events``); a
  redelivery is acknowledged and skipped.
* **Ordered** — events can arrive out of order; a subscription event older than
  the last one applied is ignored, and an old subscription's cancellation can't
  end a newer one.
* **Honest on downgrade** — only the effective plan (``organizations.plan``)
  changes; no vendors, members or history are ever removed.

``active``, ``trialing`` and ``past_due`` keep the paid plan (Stripe retries a
failed payment; the UI warns meanwhile). Any other status means Free.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AuditLog, BillingEvent, Organization, OrgBilling, User
from . import entitlements
from .billing import BillingProvider, verify_signature
from .exceptions import ConflictError, ValidationError

log = logging.getLogger(__name__)

ENTITLED_STATUSES = frozenset({"active", "trialing", "past_due"})


class WebhookPayloadError(Exception):
    """Signed, but not an event we can read."""


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def get_billing_row(db: Session, org_id: int) -> OrgBilling | None:
    return db.scalar(select(OrgBilling).where(OrgBilling.org_id == org_id))


def _get_or_create(db: Session, org_id: int) -> OrgBilling:
    row = get_billing_row(db, org_id)
    if row is None:
        row = OrgBilling(org_id=org_id, plan="free", cancel_at_period_end=False)
        db.add(row)
        db.flush()
    return row


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC) if value else None
    except (TypeError, ValueError):
        return None


def _org_for(
    db: Session,
    *,
    reference: Any = None,
    metadata: dict | None = None,
    customer_id: str | None = None,
) -> Organization | None:
    """Match an event to an org: our own reference / metadata first (set at
    checkout), then an already-linked customer id."""
    for raw in (reference, (metadata or {}).get("org_id")):
        if raw is not None and str(raw).isdigit():
            org = db.get(Organization, int(raw))
            if org is not None:
                return org
    if customer_id:
        row = db.scalar(select(OrgBilling).where(OrgBilling.stripe_customer_id == customer_id))
        if row is not None:
            return db.get(Organization, row.org_id)
    return None


def _subscription_price(sub: dict) -> str | None:
    items = ((sub.get("items") or {}).get("data")) or []
    price = (items[0].get("price") or {}) if items else {}
    return price.get("id") if isinstance(price, dict) else None


def _period_end(sub: dict) -> datetime | None:
    # Newer Stripe API versions moved current_period_end onto the items.
    items = ((sub.get("items") or {}).get("data")) or []
    return _ts(sub.get("current_period_end") or (items[0].get("current_period_end") if items else None))


def _audit(db: Session, org_id: int, action: str, extra: dict) -> None:
    # Recorded as the system (no actor): the provider made this change.
    db.add(AuditLog(org_id=org_id, actor_user_id=None, action=action, target_type="org",
                    target_id=str(org_id), extra=extra))


# --------------------------------------------------------------------------- #
# Webhooks                                                                     #
# --------------------------------------------------------------------------- #
def process_webhook(
    db: Session, provider: BillingProvider, payload: bytes, signature: str | None
) -> str:
    """Verify and apply one webhook delivery. Returns the outcome; raises
    ``SignatureError`` (-> 400) or ``WebhookPayloadError`` (-> 400)."""
    verify_signature(payload, signature, provider.webhook_secret)
    try:
        event = json.loads(payload)
    except ValueError as exc:
        raise WebhookPayloadError("body is not JSON") from exc
    if not isinstance(event, dict) or not event.get("id") or not event.get("type"):
        raise WebhookPayloadError("not an event")
    return apply_event(db, provider, event)


def apply_event(db: Session, provider: BillingProvider, event: dict) -> str:
    record = BillingEvent(event_id=str(event["id"])[:255], type=str(event["type"])[:100])
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.info("billing event %s already processed", event["id"])
        return "duplicate"

    obj = (event.get("data") or {}).get("object") or {}
    created = _ts(event.get("created")) or datetime.now(UTC)
    etype = record.type
    if etype == "checkout.session.completed":
        outcome = _checkout_completed(db, obj, record)
    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        outcome = _subscription_changed(
            db, provider, obj, created, record, deleted=etype.endswith(".deleted")
        )
    elif etype == "invoice.payment_failed":
        outcome = _payment_failed(db, obj, record)
    else:
        outcome = "ignored"  # we subscribe to more than we act on; fine

    record.outcome = outcome
    record.processed_at = datetime.now(UTC)
    db.commit()
    log.info(
        "billing event %s (%s): %s", record.event_id, etype, outcome,
        extra={"billing_event": etype, "outcome": outcome, "org_id": record.org_id},
    )
    return outcome


def _checkout_completed(db: Session, session: dict, record: BillingEvent) -> str:
    org = _org_for(db, reference=session.get("client_reference_id"),
                   metadata=session.get("metadata"), customer_id=session.get("customer"))
    if org is None:
        return "unmatched"
    record.org_id = org.id
    row = _get_or_create(db, org.id)
    if session.get("customer"):
        row.stripe_customer_id = session["customer"]
    if session.get("subscription"):
        row.stripe_subscription_id = session["subscription"]
    return "applied"


def _subscription_changed(
    db: Session,
    provider: BillingProvider,
    sub: dict,
    created: datetime,
    record: BillingEvent,
    *,
    deleted: bool,
) -> str:
    org = _org_for(db, metadata=sub.get("metadata"), customer_id=sub.get("customer"))
    if org is None:
        return "unmatched"
    record.org_id = org.id
    row = _get_or_create(db, org.id)

    if row.last_event_at is not None and created < _aware(row.last_event_at):
        return "stale"  # an older state arriving late
    sub_id = sub.get("id")
    if deleted and row.stripe_subscription_id and sub_id != row.stripe_subscription_id:
        return "stale"  # an earlier subscription ending mustn't cancel the current one

    plan = provider.plan_for_price(_subscription_price(sub))
    if plan is None:
        meta_plan = (sub.get("metadata") or {}).get("plan")
        plan = meta_plan if meta_plan in entitlements.PAID_PLANS else None
    if plan is None:
        log.warning("subscription %s has an unknown price; ignoring", sub_id)
        return "ignored"

    status = "canceled" if deleted else str(sub.get("status") or "")
    row.stripe_subscription_id = sub_id or row.stripe_subscription_id
    if sub.get("customer") and not row.stripe_customer_id:
        row.stripe_customer_id = sub["customer"]
    row.plan = plan
    row.status = status
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    row.current_period_end = _period_end(sub)
    row.last_event_at = created

    effective = plan if status in ENTITLED_STATUSES else "free"
    if org.plan != effective:
        _audit(db, org.id, "billing.plan_changed",
               {"from": org.plan, "to": effective, "status": status})
        org.plan = effective
    return "applied"


def _payment_failed(db: Session, invoice: dict, record: BillingEvent) -> str:
    details = ((invoice.get("parent") or {}).get("subscription_details")) or {}
    org = _org_for(db, metadata=details.get("metadata"), customer_id=invoice.get("customer"))
    if org is None:
        return "unmatched"
    record.org_id = org.id
    # The status change itself (-> past_due) arrives as customer.subscription.updated.
    _audit(db, org.id, "billing.payment_failed", {"attempt": invoice.get("attempt_count")})
    return "applied"


# --------------------------------------------------------------------------- #
# Owner actions                                                                #
# --------------------------------------------------------------------------- #
def has_active_subscription(row: OrgBilling | None) -> bool:
    return bool(row and row.stripe_subscription_id and row.status in ENTITLED_STATUSES)


def start_checkout(
    db: Session, org: Organization, user: User, plan: str, provider: BillingProvider
) -> str:
    if plan not in entitlements.PAID_PLANS:
        raise ValidationError("Choose the Team or Business plan.")
    row = get_billing_row(db, org.id)
    if has_active_subscription(row):
        raise ConflictError("This organization already has a subscription. "
                            "Use Manage billing to change or cancel it.")
    base = get_settings().app_base_url.rstrip("/")
    return provider.create_checkout(
        org_id=org.id,
        plan=plan,
        customer_id=row.stripe_customer_id if row else None,
        email=user.email,
        success_url=f"{base}/settings?billing=success#billing",
        cancel_url=f"{base}/settings?billing=cancelled#billing",
    )


def open_portal(db: Session, org: Organization, provider: BillingProvider) -> str:
    row = get_billing_row(db, org.id)
    if row is None or not row.stripe_customer_id:
        raise ConflictError("There's no billing account yet. Choose a plan first.")
    base = get_settings().app_base_url.rstrip("/")
    return provider.create_portal(
        org_id=org.id, customer_id=row.stripe_customer_id, return_url=f"{base}/settings#billing"
    )


def summary(db: Session, org: Organization, provider: BillingProvider | None) -> dict:
    row = get_billing_row(db, org.id)
    plan = entitlements.plan_for(org)
    members = entitlements.member_count(db, org.id)
    pending = entitlements.pending_invite_count(db, org.id)
    return {
        "plan": plan,
        "status": row.status if row else None,
        "cancel_at_period_end": bool(row and row.cancel_at_period_end),
        "current_period_end": row.current_period_end if row else None,
        "has_subscription": has_active_subscription(row),
        "has_billing_account": bool(row and row.stripe_customer_id),
        "vendors_used": entitlements.vendor_count(db, org.id),
        "members_used": members + pending,
        "members_pending": pending,
        "provider": provider.kind if provider else None,
    }
