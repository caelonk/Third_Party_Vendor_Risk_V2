"""Declarative base, naming convention, shared mixins, and enums.

A deterministic constraint-naming convention is set on the metadata so Alembic
autogenerate produces stable, reviewable migration names across runs.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """created_at / updated_at, both server-managed in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Enums (stored as strings; validated at the API boundary)                    #
# --------------------------------------------------------------------------- #
class Role(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class Theme(enum.StrEnum):
    light = "light"
    dark = "dark"
    system = "system"


class AlertType(enum.StrEnum):
    new_kev = "new_kev"
    tier_change = "tier_change"
    renewal_due = "renewal_due"


class AlertChannel(enum.StrEnum):
    email = "email"
    slack = "slack"


class NotificationStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class SyncStatus(enum.StrEnum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


class MatchMethod(enum.StrEnum):
    virtual_match = "virtual_match"
    keyword = "keyword"


class ExportFormat(enum.StrEnum):
    csv = "csv"
    pdf = "pdf"


class ExportStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    expired = "expired"  # retention elapsed; the stored file has been deleted


# --------------------------------------------------------------------------- #
# Shared SQLAlchemy Enum type objects.                                         #
#                                                                             #
# ``native_enum=False`` stores these as VARCHAR + a CHECK constraint on both   #
# Postgres and SQLite, rather than a native PG ENUM type. That keeps values    #
# validated at the DB while avoiding native-enum migration pain (ALTER TYPE to #
# add a value, duplicate CREATE TYPE when one enum is used by several tables). #
# The instances are shared so every column uses an identical definition.       #
# --------------------------------------------------------------------------- #
role_enum = Enum(Role, name="role", native_enum=False)
theme_enum = Enum(Theme, name="theme", native_enum=False)
alert_type_enum = Enum(AlertType, name="alert_type", native_enum=False)
alert_channel_enum = Enum(AlertChannel, name="alert_channel", native_enum=False)
notification_status_enum = Enum(NotificationStatus, name="notification_status", native_enum=False)
sync_status_enum = Enum(SyncStatus, name="sync_status", native_enum=False)
match_method_enum = Enum(MatchMethod, name="match_method", native_enum=False)
export_format_enum = Enum(ExportFormat, name="export_format", native_enum=False)
export_status_enum = Enum(ExportStatus, name="export_status", native_enum=False)
