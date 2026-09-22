"""Risk model: threat band x exposure band -> final tier.

The final tier is a **literal lookup matrix**, not arithmetic — it is
intentionally non-multiplicative (e.g. KEV floors at ``High`` rather than being
forced to ``Critical``) and must stay editable. Unscored (NULL) CVSS values
never count toward the CVSS thresholds; a missing score is not a zero.
"""
from __future__ import annotations

THREAT_BANDS = ("T1", "T2", "T3", "T4")
EXPOSURE_BANDS = ("E1", "E2", "E3", "E4")
NOT_ASSESSED = "Not Assessed"

# Final tier lookup (spec section 5). Rows = threat, columns = exposure.
MATRIX: dict[tuple[str, str], str] = {
    ("T4", "E1"): "High",   ("T4", "E2"): "High",   ("T4", "E3"): "Critical", ("T4", "E4"): "Critical",
    ("T3", "E1"): "Medium", ("T3", "E2"): "High",   ("T3", "E3"): "High",     ("T3", "E4"): "Critical",
    ("T2", "E1"): "Low",    ("T2", "E2"): "Medium", ("T2", "E3"): "Medium",   ("T2", "E4"): "High",
    ("T1", "E1"): "Low",    ("T1", "E2"): "Low",    ("T1", "E3"): "Low",      ("T1", "E4"): "Medium",
}

TIER_ORDER = ["Not Assessed", "Low", "Medium", "High", "Critical"]


def _scores(cves) -> list[float]:
    """CVSS scores that actually exist — NULLs are excluded, never treated as 0."""
    return [c["cvss_score"] for c in cves if c.get("cvss_score") is not None]


def max_cvss(cves) -> float | None:
    scores = _scores(cves)
    return max(scores) if scores else None


def threat_band(cves) -> str:
    """T4 KEV present; else T3 (max>=9 or >=3 CVEs>=7); else T2 (max>=7); else T1."""
    if any(c.get("is_kev") for c in cves):
        return "T4"
    scores = _scores(cves)
    top = max(scores) if scores else None
    high_count = sum(1 for s in scores if s >= 7.0)
    if (top is not None and top >= 9.0) or high_count >= 3:
        return "T3"
    if top is not None and top >= 7.0:
        return "T2"
    return "T1"


def exposure_band(vendor) -> str:
    """Highest matching band wins (evaluated E4 -> E1)."""
    acv = vendor.get("annual_contract_value") or 0
    sensitivity = (vendor.get("data_sensitivity") or "").lower()
    criticality = (vendor.get("business_criticality") or "").lower()
    if sensitivity == "regulated" or acv >= 500_000:
        return "E4"
    if sensitivity == "confidential" or acv >= 100_000 or criticality == "high":
        return "E3"
    if acv >= 25_000:
        return "E2"
    return "E1"


def final_tier(vendor, cves) -> str:
    """Unmapped/failed vendors are 'Not Assessed' and never enter the matrix."""
    if not vendor.get("is_mapped"):
        return NOT_ASSESSED
    return MATRIX[(threat_band(cves), exposure_band(vendor))]


def assess(vendor, cves) -> dict:
    """Full per-vendor assessment for the dashboard (bands are None if unmapped)."""
    mapped = bool(vendor.get("is_mapped"))
    tband = threat_band(cves) if mapped else None
    eband = exposure_band(vendor) if mapped else None
    return {
        "vendor_name": vendor.get("vendor_name"),
        "tier": MATRIX[(tband, eband)] if mapped else NOT_ASSESSED,
        "threat_band": tband,
        "exposure_band": eband,
        "max_cvss": max_cvss(cves),
        "cve_count": len(cves),
        "kev_count": sum(1 for c in cves if c.get("is_kev")),
        "is_mapped": mapped,
        "annual_contract_value": vendor.get("annual_contract_value"),
        "data_sensitivity": vendor.get("data_sensitivity"),
        "business_criticality": vendor.get("business_criticality"),
        "contract_renewal_date": vendor.get("contract_renewal_date"),
        "match_method": vendor.get("match_method"),
    }
