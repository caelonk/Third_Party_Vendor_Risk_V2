"""Billing: the provider's webhook, the org's plan summary, and owner actions.

* ``POST /billing/webhook`` — public; authenticated by the Stripe signature.
* ``GET /orgs/{id}/billing`` — plan, status, usage vs limits (any member).
* ``POST /orgs/{id}/billing/checkout`` / ``/portal`` — owner only; return a URL
  on the provider's hosted pages for a full-page redirect.

The development stand-in's checkout and billing-portal pages live under
``/billing/dev`` and are 404 unless the stand-in is the active provider.
"""
from __future__ import annotations

import html
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context, require_role
from ..models import Organization, Role, User
from ..schemas.billing import BillingOut, CheckoutIn, PlanOut, RedirectOut, UsageOut
from ..security import decode_token
from ..services import audit_service, billing, billing_service, entitlements
from ..services.billing import BillingProvider, DevBilling, SignatureError
from ..services.billing_service import WebhookPayloadError
from ..services.exceptions import UnavailableError
from . import _dev_pages

log = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])


def get_billing_provider() -> BillingProvider | None:
    return billing.get_billing()


def _require(provider: BillingProvider | None) -> BillingProvider:
    if provider is None:
        raise UnavailableError("Billing isn't configured on this server.")
    return provider


def _plan_out(plan: entitlements.Plan) -> PlanOut:
    return PlanOut(
        id=plan.id, name=plan.name, price_usd_month=plan.price_usd_month,
        max_vendors=plan.max_vendors, max_members=plan.max_members,
        min_sync_hours=plan.min_sync_hours, pdf_reports=plan.pdf_reports,
    )


# --------------------------------------------------------------------------- #
# Webhook                                                                      #
# --------------------------------------------------------------------------- #
@router.post("/billing/webhook", include_in_schema=False)
async def billing_webhook(
    request: Request,
    provider: BillingProvider | None = Depends(get_billing_provider),
    db: Session = Depends(get_session),
) -> dict:
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    payload = await request.body()  # the exact bytes that were signed
    signature = request.headers.get("stripe-signature")
    try:
        outcome = await run_in_threadpool(
            billing_service.process_webhook, db, provider, payload, signature
        )
    except SignatureError as exc:
        log.warning("billing webhook rejected: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature") from exc
    except WebhookPayloadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"received": True, "outcome": outcome}


# --------------------------------------------------------------------------- #
# Org billing                                                                  #
# --------------------------------------------------------------------------- #
@router.get("/orgs/{org_id}/billing", response_model=BillingOut)
def get_billing_summary(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    provider: BillingProvider | None = Depends(get_billing_provider),
) -> BillingOut:
    s = billing_service.summary(db, ctx.organization, provider)
    plan: entitlements.Plan = s["plan"]
    return BillingOut(
        plan=_plan_out(plan),
        status=s["status"],
        cancel_at_period_end=s["cancel_at_period_end"],
        current_period_end=s["current_period_end"],
        has_subscription=s["has_subscription"],
        has_billing_account=s["has_billing_account"],
        vendors=UsageOut(used=s["vendors_used"], limit=plan.max_vendors),
        members=UsageOut(used=s["members_used"], limit=plan.max_members),
        members_pending=s["members_pending"],
        provider=s["provider"],
        plans=[_plan_out(entitlements.PLANS[p]) for p in entitlements.PLAN_ORDER],
    )


@router.post("/orgs/{org_id}/billing/checkout", response_model=RedirectOut)
def start_checkout(
    body: CheckoutIn,
    ctx: OrgContext = Depends(require_role(Role.owner)),
    db: Session = Depends(get_session),
    provider: BillingProvider | None = Depends(get_billing_provider),
) -> RedirectOut:
    user = db.get(User, ctx.membership.user_id)
    assert user is not None
    url = billing_service.start_checkout(db, ctx.organization, user, body.plan, _require(provider))
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=user.id,
        action="billing.checkout_started", target_type="org", target_id=ctx.organization.id,
        extra={"plan": body.plan},
    )
    return RedirectOut(url=url)


@router.post("/orgs/{org_id}/billing/portal", response_model=RedirectOut)
def open_portal(
    ctx: OrgContext = Depends(require_role(Role.owner)),
    db: Session = Depends(get_session),
    provider: BillingProvider | None = Depends(get_billing_provider),
) -> RedirectOut:
    return RedirectOut(url=billing_service.open_portal(db, ctx.organization, _require(provider)))


# --------------------------------------------------------------------------- #
# Development stand-in: "Stripe Checkout" and "Billing portal" pages          #
# --------------------------------------------------------------------------- #
def _dev(provider: BillingProvider | None = Depends(get_billing_provider)) -> DevBilling:
    if not isinstance(provider, DevBilling):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return provider


def _claims(token: str, kind: str) -> dict[str, Any]:
    try:
        claims = decode_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link has expired. Start again from Settings.") from exc
    if claims.get("type") != kind:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid link")
    return claims


def _send(db: Session, dev: DevBilling, event: dict) -> str:
    """Deliver a stand-in event through the real webhook path (signed, verified)."""
    payload, signature = dev.signed(event)
    return billing_service.process_webhook(db, dev, payload, signature)


def _money(plan: entitlements.Plan) -> str:
    return f"${plan.price_usd_month}/month"


@router.get("/billing/dev/checkout", include_in_schema=False)
def dev_checkout_page(
    token: str = Query(..., max_length=4096),
    _dev_provider: DevBilling = Depends(_dev),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    claims = _claims(token, "dev_checkout")
    plan = entitlements.PLANS[claims["plan"]]
    org = db.get(Organization, claims["org_id"])
    esc = html.escape
    body = f"""<h1>Subscribe to {esc(plan.name)}</h1>
  <p>This page stands in for Stripe Checkout because no Stripe keys are configured.
     Nothing is charged; subscribing sends the same signed webhook events Stripe would.</p>
  <dl>
    <dt>Organization</dt><dd>{esc(org.name if org else "—")}</dd>
    <dt>Plan</dt><dd>{esc(plan.name)} · {esc(_money(plan))} (demo)</dd>
    <dt>Card</dt><dd class="mono">4242 4242 4242 4242 (simulated)</dd>
  </dl>
  <form method="get" action="/api/v1/billing/dev/checkout/complete">
    <input type="hidden" name="token" value="{esc(token)}">
    <div class="row">
      <button type="submit" name="action" value="cancel">Cancel</button>
      <button type="submit" name="action" value="pay" class="primary">Subscribe</button>
    </div>
  </form>"""
    return _dev_pages.render("Checkout (development stand-in)", body)


@router.get("/billing/dev/checkout/complete", include_in_schema=False)
def dev_checkout_complete(
    token: str = Query(..., max_length=4096),
    action: str = Query(default="pay", max_length=20),
    dev: DevBilling = Depends(_dev),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    claims = _claims(token, "dev_checkout")
    if action != "pay":
        return RedirectResponse(claims["cancel_url"], status_code=302)
    org_id = int(claims["org_id"])
    # Paying twice (back button, double click) must not open a second subscription.
    if billing_service.has_active_subscription(billing_service.get_billing_row(db, org_id)):
        return RedirectResponse(claims["success_url"], status_code=302)

    customer = claims.get("customer_id") or dev.new_id("cus")
    subscription = dev.new_id("sub")
    period_end = int(datetime.now(UTC).timestamp()) + billing.DEV_PERIOD_SECONDS
    _send(db, dev, dev.event("checkout.session.completed", {
        "id": dev.new_id("cs"), "object": "checkout.session", "mode": "subscription",
        "status": "complete", "client_reference_id": str(org_id), "customer": customer,
        "subscription": subscription, "metadata": {"org_id": str(org_id), "plan": claims["plan"]},
    }))
    _send(db, dev, dev.event("customer.subscription.created", dev.subscription(
        subscription_id=subscription, customer_id=customer, org_id=org_id,
        plan=claims["plan"], status="active", period_end=period_end,
    )))
    return RedirectResponse(claims["success_url"], status_code=302)


_PORTAL_ACTIONS = {
    "switch_team": "Switched to the Team plan.",
    "switch_business": "Switched to the Business plan.",
    "cancel_at_period_end": "The subscription will end at the close of this period.",
    "resume": "The subscription will renew as usual.",
    "cancel_now": "The subscription is canceled; the organization is back on Free.",
    "fail_payment": "Simulated a failed renewal payment: the subscription is past due.",
    "recover_payment": "Simulated a successful retry: the subscription is active again.",
}


@router.get("/billing/dev/portal", include_in_schema=False)
def dev_portal_page(
    token: str = Query(..., max_length=4096),
    done: str | None = Query(default=None, max_length=40),
    _dev_provider: DevBilling = Depends(_dev),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    claims = _claims(token, "dev_portal")
    org = db.get(Organization, claims["org_id"])
    row = billing_service.get_billing_row(db, int(claims["org_id"]))
    esc = html.escape
    notice = (f'<div class="notice" role="status">{esc(_PORTAL_ACTIONS[done])}</div>'
              if done in _PORTAL_ACTIONS else "")
    back = f'<a class="button" href="{esc(claims["return_url"])}">Return to Vendor Risk</a>'

    active = billing_service.has_active_subscription(row)
    if not active or row is None:
        body = f"""<h1>Billing portal</h1>
  {notice}
  <p>{esc(org.name if org else "This organization")} has no active subscription.
     Choose a plan from Settings to start one.</p>
  <div class="stack">{back}</div>"""
        return _dev_pages.render("Billing portal (development stand-in)", body)

    plan = entitlements.PLANS.get(row.plan, entitlements.PLANS["free"])
    period_end = row.current_period_end.strftime("%b %d, %Y") if row.current_period_end else "—"

    def button(action: str, label: str, cls: str = "") -> str:
        return (f'<button type="submit" name="action" value="{action}" class="{cls}">'
                f'{esc(label)}</button>')

    buttons = []
    for other in ("team", "business"):
        if other != row.plan:
            buttons.append(button(f"switch_{other}", f"Switch to {entitlements.PLANS[other].name}"))
    if row.status == "past_due":
        buttons.append(button("recover_payment", "Simulate successful payment retry", "primary"))
    else:
        buttons.append(button("fail_payment", "Simulate failed renewal payment"))
    buttons.append(button("resume", "Resume subscription") if row.cancel_at_period_end
                   else button("cancel_at_period_end", "Cancel at period end"))
    buttons.append(button("cancel_now", "Cancel now", "danger"))

    body = f"""<h1>Billing portal</h1>
  <p>This page stands in for the Stripe customer portal. Each action sends the
     signed webhook events Stripe would send for it.</p>
  {notice}
  <dl>
    <dt>Organization</dt><dd>{esc(org.name if org else "—")}</dd>
    <dt>Plan</dt><dd>{esc(plan.name)} · {esc(_money(plan))} (demo)</dd>
    <dt>Status</dt><dd>{esc((row.status or "").replace("_", " "))}</dd>
    <dt>{"Ends" if row.cancel_at_period_end else "Renews"}</dt><dd>{esc(period_end)}</dd>
    <dt>Customer</dt><dd class="mono">{esc(row.stripe_customer_id or "—")}</dd>
  </dl>
  <form method="get" action="/api/v1/billing/dev/portal/action">
    <input type="hidden" name="token" value="{esc(token)}">
    <div class="stack">{"".join(buttons)}</div>
  </form>
  <div class="stack" style="margin-top:10px">{back}</div>"""
    return _dev_pages.render("Billing portal (development stand-in)", body)


@router.get("/billing/dev/portal/action", include_in_schema=False)
def dev_portal_action(
    token: str = Query(..., max_length=4096),
    action: str = Query(..., max_length=40),
    dev: DevBilling = Depends(_dev),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    claims = _claims(token, "dev_portal")
    if action not in _PORTAL_ACTIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown action")
    org_id = int(claims["org_id"])
    row = billing_service.get_billing_row(db, org_id)
    if billing_service.has_active_subscription(row) and row is not None:
        state = {
            "plan": row.plan,
            "status": row.status or "active",
            "cancel_at_period_end": row.cancel_at_period_end,
        }
        period_end = int((row.current_period_end or datetime.now(UTC)).timestamp())
        event_type = "customer.subscription.updated"
        if action.startswith("switch_"):
            state["plan"] = action.removeprefix("switch_")
        elif action == "cancel_at_period_end":
            state["cancel_at_period_end"] = True
        elif action == "resume":
            state["cancel_at_period_end"] = False
        elif action == "cancel_now":
            event_type, state["status"] = "customer.subscription.deleted", "canceled"
        elif action == "fail_payment":
            state["status"] = "past_due"
            _send(db, dev, dev.event("invoice.payment_failed", {
                "id": dev.new_id("in"), "object": "invoice", "customer": row.stripe_customer_id,
                "attempt_count": 1,
                "parent": {"subscription_details": {
                    "subscription": row.stripe_subscription_id,
                    "metadata": {"org_id": str(org_id), "plan": row.plan},
                }},
            }))
        elif action == "recover_payment":
            state["status"] = "active"
        _send(db, dev, dev.event(event_type, dev.subscription(
            subscription_id=row.stripe_subscription_id or dev.new_id("sub"),
            customer_id=row.stripe_customer_id or dev.new_id("cus"),
            org_id=org_id, plan=str(state["plan"]), status=str(state["status"]),
            period_end=period_end, cancel_at_period_end=bool(state["cancel_at_period_end"]),
        )))
    target = f"/api/v1/billing/dev/portal?{urlencode({'token': token, 'done': action})}"
    return RedirectResponse(target, status_code=303)
