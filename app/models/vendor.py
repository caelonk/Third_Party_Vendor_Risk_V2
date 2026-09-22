"""Per-org vendors, the vendor<->CVE junction, and append-only risk snapshots."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, MatchMethod, TimestampMixin, match_method_enum


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    cpe_prefix: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    match_method: Mapped[MatchMethod | None] = mapped_column(match_method_enum, nullable=True)
    is_mapped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Business context (per-tenant exposure inputs).
    annual_contract_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_sensitivity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    business_criticality: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contract_renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    links: Mapped[list[VendorVulnerability]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list[RiskSnapshot]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )


class VendorVulnerability(Base):
    __tablename__ = "vendor_vulnerabilities"

    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True
    )
    cve_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerabilities.cve_id", ondelete="CASCADE"), primary_key=True
    )

    vendor: Mapped[Vendor] = relationship(back_populates="links")


class RiskSnapshot(Base):
    """Append-only time series powering trends and audit history."""

    __tablename__ = "risk_snapshots"
    __table_args__ = (Index("ix_risk_snapshots_vendor_captured", "vendor_id", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    threat_band: Mapped[str | None] = mapped_column(String(4), nullable=True)
    exposure_band: Mapped[str | None] = mapped_column(String(4), nullable=True)
    max_cvss: Mapped[float | None] = mapped_column(Float, nullable=True)
    cve_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kev_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vendor: Mapped[Vendor] = relationship(back_populates="snapshots")
