"""Assess a vendor from its stored CVEs using the pure ``core.scoring`` model."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import scoring

from ..models import Vendor, VendorVulnerability, Vulnerability

_IN_CHUNK = 500  # bound IN-list size (SQLite variable limits, sane Postgres plans)


def _cve_dict(r: Vulnerability) -> dict:
    return {
        "cve_id": r.cve_id,
        "cvss_score": r.cvss_score,   # None stays None, never 0.0
        "cvss_severity": r.cvss_severity,
        "is_kev": r.is_kev,
        "published_date": r.published_date,
    }


def cves_for_vendor(db: Session, vendor_id: int) -> list[dict]:
    """The vendor's linked CVEs as plain dicts for the scoring functions."""
    return cves_for_vendors(db, [vendor_id])[vendor_id]


def cves_for_vendors(db: Session, vendor_ids: list[int]) -> dict[int, list[dict]]:
    """Linked CVEs for many vendors, grouped by vendor id — one query per 500
    vendors instead of one per vendor (the N+1 the list/dashboard/export paths
    used to hit)."""
    grouped: dict[int, list[dict]] = {vid: [] for vid in vendor_ids}
    for i in range(0, len(vendor_ids), _IN_CHUNK):
        chunk = vendor_ids[i : i + _IN_CHUNK]
        rows = db.execute(
            select(VendorVulnerability.vendor_id, Vulnerability)
            .join(Vulnerability, VendorVulnerability.cve_id == Vulnerability.cve_id)
            .where(VendorVulnerability.vendor_id.in_(chunk))
        ).all()
        for vendor_id, vuln in rows:
            grouped[vendor_id].append(_cve_dict(vuln))
    return grouped


def vendor_to_dict(vendor: Vendor) -> dict:
    return {
        "vendor_name": vendor.name,
        "is_mapped": vendor.is_mapped,
        "annual_contract_value": vendor.annual_contract_value,
        "data_sensitivity": vendor.data_sensitivity,
        "business_criticality": vendor.business_criticality,
        "contract_renewal_date": (
            vendor.contract_renewal_date.isoformat() if vendor.contract_renewal_date else None
        ),
        "match_method": vendor.match_method.value if vendor.match_method else None,
    }


def assess_vendor(db: Session, vendor: Vendor) -> dict:
    """Full assessment dict (tier, bands, counts) for one vendor."""
    cves = cves_for_vendor(db, vendor.id)
    return scoring.assess(vendor_to_dict(vendor), cves)


def assess_vendors(db: Session, vendors: list[Vendor]) -> dict[int, dict]:
    """Assessments for many vendors, keyed by vendor id, with one batched CVE fetch.

    Identical results to calling :func:`assess_vendor` per vendor — the same pure
    ``core.scoring.assess`` runs on each group; only the data loading changes.
    """
    cves = cves_for_vendors(db, [v.id for v in vendors])
    return {v.id: scoring.assess(vendor_to_dict(v), cves[v.id]) for v in vendors}
