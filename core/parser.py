"""Normalize raw NVD CVE JSON into flat records for the database.

Two rules matter most here (Integrity Rule 1): a missing CVSS score becomes
``None`` and is *never* coalesced to ``0.0``; and parsing must not raise on a
record that lacks ``descriptions``, ``published``, or ``metrics``.
"""
from __future__ import annotations

from collections.abc import Iterator

# CVSS fallback chain, highest-priority first. The version string is decided by
# which metric array is present, per spec section 6.
CVSS_CHAIN: list[tuple[str, str]] = [
    ("cvssMetricV40", "4.0"),
    ("cvssMetricV31", "3.1"),
    ("cvssMetricV30", "3.0"),
    ("cvssMetricV2", "2.0"),
]


def extract_cvss(metrics: dict | None) -> tuple[float | None, str | None, str | None]:
    """Return (base_score, version, severity) using the fallback chain.

    Returns (None, None, None) when no metric block is present. Severity comes
    from ``cvssData.baseSeverity`` (v3/v4) or the metric-level ``baseSeverity``
    (v2 keeps it there, since CVSS v2 base data has no severity field).
    """
    metrics = metrics or {}
    for key, version in CVSS_CHAIN:
        entries = metrics.get(key) or []
        if not entries:
            continue
        entry = entries[0] or {}
        cvss_data = entry.get("cvssData") or {}
        score = cvss_data.get("baseScore")
        severity = cvss_data.get("baseSeverity") or entry.get("baseSeverity")
        return score, version, severity
    return None, None, None


def extract_kev(cve: dict) -> tuple[bool, str | None, str | None]:
    """A CVE is KEV iff ``cisaExploitAdd`` is present on the record."""
    added = cve.get("cisaExploitAdd")
    if added:
        return True, added, cve.get("cisaActionDue")
    return False, None, None


def extract_description(cve: dict) -> str | None:
    descriptions = cve.get("descriptions") or []
    english = [d for d in descriptions if d.get("lang") == "en"]
    chosen = english[0] if english else (descriptions[0] if descriptions else None)
    return chosen.get("value") if chosen else None


def parse_cve(cve: dict) -> dict:
    """Normalize one NVD ``cve`` object into a flat record dict."""
    score, version, severity = extract_cvss(cve.get("metrics"))
    is_kev, kev_added, kev_due = extract_kev(cve)
    return {
        "cve_id": cve.get("id"),
        "cvss_score": score,           # None (never 0.0) when unscored
        "cvss_version": version,
        "cvss_severity": severity,
        "is_kev": 1 if is_kev else 0,
        "kev_date_added": kev_added,
        "kev_due_date": kev_due,
        "published_date": cve.get("published"),
        "vuln_status": cve.get("vulnStatus"),
        "description": extract_description(cve),
    }


def iter_cve_objects(payload: dict) -> Iterator[dict]:
    """Yield inner ``cve`` objects from an NVD response payload."""
    for item in payload.get("vulnerabilities") or []:
        cve = item.get("cve") if isinstance(item, dict) else None
        if cve:
            yield cve


def parse_response(payload: dict) -> list[dict]:
    """Parse a whole NVD response into normalized records (skips id-less rows)."""
    records = [parse_cve(cve) for cve in iter_cve_objects(payload)]
    return [r for r in records if r["cve_id"]]
