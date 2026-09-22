"""Assess a vendor from its stored CVEs using the pure ``core.scoring`` model."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import scoring

from ..models import Vendor, VendorVulnerability, Vulnerability


def cves_for_vendor(db: Session, vendor_id: int) -> list[dict]:
    """The vendor's linked CVEs as plain dicts for the scoring functions."""
    rows = db.scalars(
        select(Vulnerability)
        .join(VendorVulnerability, VendorVulnerability.cve_id == Vulnerability.cve_id)
        .where(VendorVulnerability.vendor_id == vendor_id)
    ).all()
    return [
        {
            "cve_id": r.cve_id,
            "cvss_score": r.cvss_score,   # None stays None, never 0.0
            "cvss_severity": r.cvss_severity,
            "is_kev": r.is_kev,
            "published_date": r.published_date,
        }
        for r in rows
    ]


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
