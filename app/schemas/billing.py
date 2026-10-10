"""Billing DTOs: plan catalog, the org's billing summary, and redirect URLs."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PlanOut(BaseModel):
    id: str
    name: str
    price_cents: int  # monthly, in US cents
    max_vendors: int | None  # None = unlimited
    max_members: int | None
    min_sync_hours: int
    pdf_reports: bool


class UsageOut(BaseModel):
    used: int
    limit: int | None  # None = unlimited


class BillingOut(BaseModel):
    plan: PlanOut
    status: str | None  # provider status; None = no subscription (plan assigned directly)
    cancel_at_period_end: bool
    current_period_end: datetime | None
    has_subscription: bool
    has_billing_account: bool
    vendors: UsageOut
    members: UsageOut  # members + pending invitations
    members_pending: int
    provider: str | None  # "stripe_test" | "stripe_live" | "dev_stand_in" | None (billing off)
    plans: list[PlanOut]


class CheckoutIn(BaseModel):
    plan: Literal["team", "business"]


class RedirectOut(BaseModel):
    url: str
