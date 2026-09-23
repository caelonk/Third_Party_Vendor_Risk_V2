"""Alert rules and dispatched notifications."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    AlertChannel,
    AlertType,
    Base,
    NotificationStatus,
    TimestampMixin,
    alert_channel_enum,
    alert_type_enum,
    notification_status_enum,
)

JSONVariant = JSON().with_variant(JSONB, "postgresql")


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[AlertType] = mapped_column(alert_type_enum, nullable=False)
    channel: Mapped[AlertChannel] = mapped_column(alert_channel_enum, nullable=False)
    # e.g. {"days": 90} for renewal_due, or a destination email address.
    config: Mapped[dict] = mapped_column(JSONVariant, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Notification(Base, TimestampMixin):
    """A dispatched alert. ``dedup_key`` makes a re-sync idempotent."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[AlertType] = mapped_column(alert_type_enum, nullable=False)
    # org:vendor:type:cve:date — unique so duplicate alerts are never produced.
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        notification_status_enum, nullable=False, default=NotificationStatus.pending
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # In-app read state (separate from dispatch status).
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
