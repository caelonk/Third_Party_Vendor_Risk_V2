"""Billing state mirrored from the payment provider (Stripe, or its dev stand-in).

The provider is the source of truth for subscriptions; these rows are what our
webhook handler last learned. ``organizations.plan`` holds the resulting
*effective* plan that the rest of the app enforces (see services/entitlements).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class OrgBilling(Base, TimestampMixin):
    __tablename__ = "org_billing"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    # The plan the subscription is for, and its provider status (active,
    # trialing, past_due, canceled, unpaid, incomplete, ...).
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ``created`` of the newest subscription event applied: webhooks can arrive
    # out of order, and an older state must never overwrite a newer one.
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingEvent(Base):
    """One row per provider event id: makes webhook delivery idempotent (the
    provider retries, and may deliver the same event more than once)."""

    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # applied | stale | ignored | unmatched
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
