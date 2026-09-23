"""Risk trends derived from the append-only ``risk_snapshots`` time series.

Every sync appends one snapshot per vendor (see :mod:`sync_service`), so history
accumulates over time. These read helpers turn that history into per-vendor and
portfolio trend series for the UI.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.constants import TIER_ORDER

from ..models import RiskSnapshot, Vendor


def vendor_trend(db: Session, org_id: int, vendor_id: int) -> list[dict]:
    """One vendor's snapshots over time (oldest first)."""
    rows = db.scalars(
        select(RiskSnapshot)
        .join(Vendor, Vendor.id == RiskSnapshot.vendor_id)
        .where(Vendor.org_id == org_id, RiskSnapshot.vendor_id == vendor_id)
        .order_by(RiskSnapshot.captured_at)
    ).all()
    return [
        {
            "captured_at": s.captured_at.isoformat(),
            "tier": s.tier,
            "max_cvss": s.max_cvss,
            "cve_count": s.cve_count,
            "kev_count": s.kev_count,
        }
        for s in rows
    ]


def portfolio_trend(db: Session, org_id: int, *, days: int = 90) -> list[dict]:
    """Portfolio totals per snapshot-day.

    For each day that has any snapshot, aggregate the latest snapshot per vendor
    as of that day: total CVEs, count of KEV-exposed vendors, and the tier
    distribution. Days without snapshots are omitted (the chart interpolates).
    """
    rows = db.scalars(
        select(RiskSnapshot)
        .join(Vendor, Vendor.id == RiskSnapshot.vendor_id)
        .where(Vendor.org_id == org_id)
        .order_by(RiskSnapshot.captured_at)
    ).all()
    if not rows:
        return []

    def as_date(s: RiskSnapshot) -> date:
        return s.captured_at.date()

    all_days = sorted({as_date(s) for s in rows})
    cutoff = all_days[-1]
    horizon = [d for d in all_days if (cutoff - d).days <= days]

    series: list[dict] = []
    for d in horizon:
        latest: dict[int, RiskSnapshot] = {}
        for s in rows:  # ordered by captured_at, so the last <= d wins
            if as_date(s) <= d:
                latest[s.vendor_id] = s
        snaps = list(latest.values())
        dist = dict.fromkeys(TIER_ORDER, 0)
        for s in snaps:
            dist[s.tier] = dist.get(s.tier, 0) + 1
        series.append(
            {
                "date": d.isoformat(),
                "total_cves": sum(s.cve_count for s in snaps),
                "kev_vendors": sum(1 for s in snaps if s.kev_count > 0),
                "tier_distribution": dist,
            }
        )
    return series
