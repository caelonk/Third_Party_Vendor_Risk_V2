"""Users, their external sign-in identities, and per-user preferences (theme +
customizable dashboard layout)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Theme, TimestampMixin, theme_enum

if TYPE_CHECKING:
    from .org import Membership

# JSONB on Postgres, JSON elsewhere (SQLite in tests).
JSONVariant = JSON().with_variant(JSONB, "postgresql")

# Per-user home dashboard: an ordered list of at most this many widgets. The
# limit is enforced in the service layer, not only the UI.
MAX_DASHBOARD_WIDGETS = 5


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # Null for accounts that only sign in through an identity provider (Google).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[UserPreference | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    identities: Mapped[list[UserIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserIdentity(Base, TimestampMixin):
    """An external sign-in (e.g. Google) linked to a user.

    Matched on the provider's stable subject id (OIDC ``sub``), never on email:
    an address can change or be reassigned; ``sub`` cannot. ``email`` records
    what the provider asserted at the last sign-in, for display and audit.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        # One account per provider per user: a second Google account can't
        # silently attach to a user who already linked one.
        UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="identities")


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[Theme] = mapped_column(theme_enum, nullable=False, default=Theme.system)
    # Ordered list of widget descriptors: [{type, config, size, expanded, order}].
    # Length is capped at MAX_DASHBOARD_WIDGETS in the service layer.
    dashboard_layout: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)

    user: Mapped[User] = relationship(back_populates="preferences")
