"""Org dashboard aggregations (widget data), all derived from one pass of
per-vendor assessments so the honest-data rules hold uniformly.

Reference date for the renewal watchlist defaults to today; it is injectable for
deterministic tests.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from core import scoring
from core.constants import TIER_ORDER, WATCHLIST_TIERS, WATCHLIST_WINDOW_DAYS

from ..models import Vendor
from . import scoring_service, vendor_service


def _assessments(db: Session, org_id: int) -> list[tuple[Vendor, dict]]:
    vendors = vendor_service.list_vendors(db, org_id)
    assessed = scoring_service.assess_vendors(db, vendors)  # one batched CVE query
    return [(v, assessed[v.id]) for v in vendors]


def summary(db: Session, org_id: int) -> dict:
    rows = _assessments(db, org_id)
    tiers = dict.fromkeys(TIER_ORDER, 0)
    kev_exposed = 0
    total_cves = 0
    for _v, a in rows:
        tiers[a["tier"]] = tiers.get(a["tier"], 0) + 1
        if a["kev_count"]:
            kev_exposed += 1
        total_cves += a["cve_count"]
    return {
        "vendor_count": len(rows),
        "mapped_count": sum(1 for _v, a in rows if a["is_mapped"]),
        "tier_distribution": tiers,
        "kev_exposed_vendors": kev_exposed,
        "total_cves": total_cves,
    }


def heatmap(db: Session, org_id: int) -> dict:
    cells: dict[str, dict] = {}
    for v, a in _assessments(db, org_id):
        if not a["is_mapped"]:
            continue
        key = f"{a['threat_band']}:{a['exposure_band']}"
        cell = cells.setdefault(key, {"count": 0, "vendors": []})
        cell["count"] += 1
        cell["vendors"].append(v.name)
    grid = []
    for t in reversed(scoring.THREAT_BANDS):  # T4 (highest) first
        for e in scoring.EXPOSURE_BANDS:
            cell = cells.get(f"{t}:{e}", {"count": 0, "vendors": []})
            grid.append(
                {
                    "threat_band": t,
                    "exposure_band": e,
                    "tier": scoring.MATRIX[(t, e)],
                    "count": cell["count"],
                    "vendors": cell["vendors"],
                }
            )
    return {"cells": grid}


def watchlist(db: Session, org_id: int, *, reference: date | None = None) -> list[dict]:
    reference = reference or date.today()
    rows = []
    for v, a in _assessments(db, org_id):
        if a["tier"] not in WATCHLIST_TIERS or v.contract_renewal_date is None:
            continue
        days = (v.contract_renewal_date - reference).days
        if not (0 <= days <= WATCHLIST_WINDOW_DAYS):
            continue
        rows.append(
            {
                "vendor_id": v.id,
                "vendor_name": v.name,
                "tier": a["tier"],
                "contract_renewal_date": v.contract_renewal_date.isoformat(),
                "days_until_renewal": days,
                "max_cvss": a["max_cvss"],
                "kev_count": a["kev_count"],
            }
        )
    rows.sort(key=lambda r: r["days_until_renewal"])
    return rows


def top_risk(db: Session, org_id: int, *, limit: int = 5) -> list[dict]:
    rows = _assessments(db, org_id)

    def sort_key(item: tuple[Vendor, dict]):
        _v, a = item
        return (-TIER_ORDER.index(a["tier"]), -(a["max_cvss"] or 0.0))

    ranked = sorted(rows, key=sort_key)[:limit]
    return [
        {
            "vendor_id": v.id,
            "vendor_name": v.name,
            "tier": a["tier"],
            "max_cvss": a["max_cvss"],
            "cve_count": a["cve_count"],
            "kev_count": a["kev_count"],
        }
        for v, a in ranked
    ]
