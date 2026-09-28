"""Billing provider port: Stripe (test mode by design) and a local stand-in.

Both give the rest of the app the same two things:

* a hosted page to send an owner to — checkout for a new subscription, the
  billing portal for changes and cancellation; and
* webhook events in Stripe's format, signed with Stripe's scheme
  (``Stripe-Signature: t=<unix>,v1=<HMAC-SHA256>``), which one handler
  verifies and applies (:func:`app.services.billing_service.process_webhook`).

:class:`DevBilling` makes the whole lifecycle runnable without a Stripe account:
its checkout and portal pages (``/api/v1/billing/dev/...``) build the events a
real subscription would produce — including a failed payment — sign them with a
per-deployment secret, and feed them through that same handler.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlencode

import stripe

from ..config import Settings, get_settings
from ..security import create_token
from .exceptions import UnavailableError

log = logging.getLogger(__name__)

SIGNATURE_TOLERANCE_SECONDS = 300  # Stripe's default: rejects replays of old events


class SignatureError(Exception):
    """The webhook payload wasn't signed by the provider (or is too old)."""


def sign_payload(payload: bytes, secret: str, *, timestamp: int | None = None) -> str:
    """A ``Stripe-Signature`` header value for ``payload`` (Stripe's v1 scheme)."""
    ts = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(payload: bytes, header: str | None, secret: str) -> None:
    """Check a webhook signature with Stripe's own verifier (constant-time
    compare, 5-minute tolerance). Raises :class:`SignatureError`."""
    if not secret:
        raise SignatureError("no webhook secret is configured")
    try:
        stripe.WebhookSignature.verify_header(
            payload, header, secret, tolerance=SIGNATURE_TOLERANCE_SECONDS
        )
    except stripe.SignatureVerificationError as exc:
        raise SignatureError(str(exc)) from exc


class BillingProvider(Protocol):
    kind: str  # "stripe_test" | "stripe_live" | "dev_stand_in"
    webhook_secret: str

    def plan_for_price(self, price_id: str | None) -> str | None: ...

    def create_checkout(
        self,
        *,
        org_id: int,
        plan: str,
        customer_id: str | None,
        email: str | None,
        success_url: str,
        cancel_url: str,
    ) -> str: ...

    def create_portal(self, *, org_id: int, customer_id: str, return_url: str) -> str: ...


# --------------------------------------------------------------------------- #
# Stripe                                                                       #
# --------------------------------------------------------------------------- #
class StripeBilling:
    def __init__(
        self,
        *,
        secret_key: str,
        webhook_secret: str | None,
        price_team: str | None,
        price_business: str | None,
        client: Any = None,
    ) -> None:
        self.kind = "stripe_live" if secret_key.startswith(("sk_live_", "rk_live_")) else "stripe_test"
        self.webhook_secret = webhook_secret or ""
        self._prices = {plan: price for plan, price in
                        (("team", price_team), ("business", price_business)) if price}
        # Any: tests inject a stand-in client; the params are plain dicts either way.
        self._client: Any = client if client is not None else stripe.StripeClient(secret_key)

    def plan_for_price(self, price_id: str | None) -> str | None:
        return next((plan for plan, price in self._prices.items() if price == price_id), None)

    def _price(self, plan: str) -> str:
        price = self._prices.get(plan)
        if not price:
            raise UnavailableError(f"The {plan} plan has no Stripe price configured.")
        return price

    def create_checkout(
        self,
        *,
        org_id: int,
        plan: str,
        customer_id: str | None,
        email: str | None,
        success_url: str,
        cancel_url: str,
    ) -> str:
        # The org id rides on both the session and the subscription, so every
        # later event can be matched to its org even before the customer is known.
        tags = {"org_id": str(org_id), "plan": plan}
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": self._price(plan), "quantity": 1}],
            "client_reference_id": str(org_id),
            "metadata": tags,
            "subscription_data": {"metadata": tags},
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_id:
            params["customer"] = customer_id
        elif email:
            params["customer_email"] = email
        try:
            session = self._client.v1.checkout.sessions.create(params=params)
        except stripe.StripeError as exc:
            log.warning("stripe checkout failed: %s", exc)
            raise UnavailableError("Stripe is unavailable right now. Try again shortly.") from exc
        return str(session.url)

    def create_portal(self, *, org_id: int, customer_id: str, return_url: str) -> str:
        try:
            session = self._client.v1.billing_portal.sessions.create(
                params={"customer": customer_id, "return_url": return_url}
            )
        except stripe.StripeError as exc:
            log.warning("stripe portal failed: %s", exc)
            raise UnavailableError("Stripe is unavailable right now. Try again shortly.") from exc
        return str(session.url)


# --------------------------------------------------------------------------- #
# Development stand-in                                                         #
# --------------------------------------------------------------------------- #
DEV_PERIOD_SECONDS = 30 * 24 * 3600


def _dev_id(prefix: str) -> str:
    return f"{prefix}_dev_{secrets.token_hex(8)}"


class DevBilling:
    """Stands in for Stripe; see the module docstring."""

    kind = "dev_stand_in"
    PRICES = {"team": "price_dev_team", "business": "price_dev_business"}
    TOKEN_TTL_SECONDS = 1800

    def __init__(self, *, base_url: str, secret: str) -> None:
        self._base = base_url.rstrip("/")
        # Derived per deployment: without it nobody can forge a stand-in event.
        digest = hmac.new(secret.encode(), b"vendor-risk/billing-dev-webhook", hashlib.sha256)
        self.webhook_secret = "whsec_dev_" + digest.hexdigest()[:40]

    def plan_for_price(self, price_id: str | None) -> str | None:
        return next((plan for plan, price in self.PRICES.items() if price == price_id), None)

    def create_checkout(
        self,
        *,
        org_id: int,
        plan: str,
        customer_id: str | None,
        email: str | None,
        success_url: str,
        cancel_url: str,
    ) -> str:
        token = create_token(
            {"type": "dev_checkout", "org_id": org_id, "plan": plan, "customer_id": customer_id,
             "email": email, "success_url": success_url, "cancel_url": cancel_url},
            self.TOKEN_TTL_SECONDS,
        )
        return f"{self._base}/api/v1/billing/dev/checkout?{urlencode({'token': token})}"

    def create_portal(self, *, org_id: int, customer_id: str, return_url: str) -> str:
        token = create_token(
            {"type": "dev_portal", "org_id": org_id, "customer_id": customer_id,
             "return_url": return_url},
            self.TOKEN_TTL_SECONDS,
        )
        return f"{self._base}/api/v1/billing/dev/portal?{urlencode({'token': token})}"

    # -- Stripe-shaped events ------------------------------------------------ #
    @staticmethod
    def event(event_type: str, obj: dict[str, Any], *, created: int | None = None) -> dict[str, Any]:
        return {
            "id": _dev_id("evt"),
            "object": "event",
            "type": event_type,
            "created": int(time.time()) if created is None else created,
            "livemode": False,
            "data": {"object": obj},
        }

    def subscription(
        self,
        *,
        subscription_id: str,
        customer_id: str,
        org_id: int,
        plan: str,
        status: str,
        period_end: int,
        cancel_at_period_end: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": subscription_id,
            "object": "subscription",
            "customer": customer_id,
            "status": status,
            "cancel_at_period_end": cancel_at_period_end,
            "metadata": {"org_id": str(org_id), "plan": plan},
            "items": {
                "object": "list",
                "data": [{"price": {"id": self.PRICES[plan]}, "current_period_end": period_end}],
            },
        }

    def signed(self, event: dict[str, Any]) -> tuple[bytes, str]:
        payload = json.dumps(event, separators=(",", ":")).encode()
        return payload, sign_payload(payload, self.webhook_secret)

    new_id = staticmethod(_dev_id)


# --------------------------------------------------------------------------- #
# Factory                                                                      #
# --------------------------------------------------------------------------- #
def build_billing(settings: Settings) -> BillingProvider | None:
    """Stripe when a key is set (test keys only, unless explicitly allowed);
    else the stand-in if enabled outside production; else billing is off."""
    key = settings.stripe_secret_key
    if key:
        if key.startswith(("sk_live_", "rk_live_")) and not settings.stripe_allow_live:
            log.error(
                "Refusing a live Stripe key: this deployment runs Stripe in test mode "
                "only (set STRIPE_ALLOW_LIVE=true to override). Billing is disabled."
            )
            return None
        if not settings.stripe_webhook_secret:
            log.warning("STRIPE_WEBHOOK_SECRET is not set: webhooks will be rejected")
        return StripeBilling(
            secret_key=key,
            webhook_secret=settings.stripe_webhook_secret,
            price_team=settings.stripe_price_team,
            price_business=settings.stripe_price_business,
        )
    if settings.billing_dev_provider:
        if settings.is_production:
            log.error("BILLING_DEV_PROVIDER is ignored in production")
            return None
        return DevBilling(base_url=settings.app_base_url, secret=settings.jwt_secret)
    return None


@lru_cache
def get_billing() -> BillingProvider | None:
    return build_billing(get_settings())
