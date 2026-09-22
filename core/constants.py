"""Shared domain constants and integrity rules.

These values encode product rules that must be reproduced identically wherever
they surface — the API, the background worker, the frontend theme, and every
export. They live here (not in a UI module) so there is a single source of truth.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Scope disclaimer (Integrity Rule 5) — reproduced verbatim in the app footer  #
# and in every export. Kept as one contiguous string so it is never reworded.  #
# --------------------------------------------------------------------------- #
SCOPE_DISCLAIMER = (
    "This tool measures published vulnerabilities in vendor products. It does "
    "not measure whether a vendor has been breached, the vendor's internal "
    "security posture, or whether this organization is actually exposed. A high "
    'score means "investigate," not "compromised."'
)

# --------------------------------------------------------------------------- #
# Severity tiers                                                               #
# --------------------------------------------------------------------------- #
# Ordered low -> high. "Not Assessed" is a distinct state, never folded into
# "Low": absence of data is not evidence of low risk (Integrity Rule).
NOT_ASSESSED = "Not Assessed"
SEVERITY_TIERS = ("Low", "Medium", "High", "Critical")
TIER_ORDER = (NOT_ASSESSED, *SEVERITY_TIERS)

# --------------------------------------------------------------------------- #
# Watchlist rule: High/Critical vendors whose contract renews within N days.   #
# --------------------------------------------------------------------------- #
WATCHLIST_WINDOW_DAYS = 90
WATCHLIST_TIERS = ("High", "Critical")
WATCHLIST_COLUMNS = (
    "vendor_name",
    "tier",
    "contract_renewal_date",
    "days_until_renewal",
    "threat_band",
    "exposure_band",
    "max_cvss",
    "cve_count",
    "kev_count",
)

# --------------------------------------------------------------------------- #
# Vendor -> NVD match methods                                                  #
# --------------------------------------------------------------------------- #
MATCH_VIRTUAL = "virtual_match"  # matched via CPE virtualMatchString prefix
MATCH_KEYWORD = "keyword"        # fell back to NVD keyword search

# --------------------------------------------------------------------------- #
# Honest-data display helpers ("Unscored" is never 0.0).                       #
# --------------------------------------------------------------------------- #
UNSCORED_LABEL = "Unscored"      # a CVE that exists but has no CVSS base score
NO_DATA_LABEL = "—"              # no CVEs at all
