"""Users and per-user preferences (theme + customizable dashboard layout)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
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
    # Nullable so a future Google OAuth identity can link to the same user row.
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
