"""Scoring tests. Pure functions, no I/O."""
import pytest

from core import scoring

# Documented final-tier matrix — asserted independently so a typo in
# scoring.MATRIX is caught directly.
EXPECTED = {
    ("T4", "E1"): "High",   ("T4", "E2"): "High",   ("T4", "E3"): "Critical", ("T4", "E4"): "Critical",
    ("T3", "E1"): "Medium", ("T3", "E2"): "High",   ("T3", "E3"): "High",     ("T3", "E4"): "Critical",
    ("T2", "E1"): "Low",    ("T2", "E2"): "Medium", ("T2", "E3"): "Medium",   ("T2", "E4"): "High",
    ("T1", "E1"): "Low",    ("T1", "E2"): "Low",    ("T1", "E3"): "Low",      ("T1", "E4"): "Medium",
}


# --- helpers to synthesize inputs that force a target band ------------------ #
def cves_for(threat: str) -> list[dict]:
    return {
        "T4": [{"is_kev": 1, "cvss_score": None}],           # KEV present
        "T3": [{"is_kev": 0, "cvss_score": 9.5}],            # max >= 9.0
        "T2": [{"is_kev": 0, "cvss_score": 7.5}],            # max >= 7.0, single
        "T1": [{"is_kev": 0, "cvss_score": 5.0}],            # otherwise
    }[threat]


def vendor_for(exposure: str) -> dict:
    base = {"vendor_name": "V", "is_mapped": 1}
    return {
        "E4": {**base, "data_sensitivity": "regulated", "annual_contract_value": 10_000, "business_criticality": "low"},
        "E3": {**base, "data_sensitivity": "confidential", "annual_contract_value": 10_000, "business_criticality": "low"},
        "E2": {**base, "data_sensitivity": "internal", "annual_contract_value": 30_000, "business_criticality": "low"},
        "E1": {**base, "data_sensitivity": "public", "annual_contract_value": 1_000, "business_criticality": "low"},
    }[exposure]


def test_matrix_matches_documented_table():
    assert scoring.MATRIX == EXPECTED


@pytest.mark.parametrize("threat", scoring.THREAT_BANDS)
@pytest.mark.parametrize("exposure", scoring.EXPOSURE_BANDS)
def test_all_16_cells(threat, exposure):
    # Sanity: our synthesizers really produce the intended bands.
    assert scoring.threat_band(cves_for(threat)) == threat
    assert scoring.exposure_band(vendor_for(exposure)) == exposure
    tier = scoring.final_tier(vendor_for(exposure), cves_for(threat))
    assert tier == EXPECTED[(threat, exposure)]


@pytest.mark.parametrize("exposure", scoring.EXPOSURE_BANDS)
def test_kev_vendor_never_below_high(exposure):
    tier = scoring.final_tier(vendor_for(exposure), cves_for("T4"))
    assert tier in ("High", "Critical")


def test_t1_e4_is_medium_not_low():
    assert scoring.final_tier(vendor_for("E4"), cves_for("T1")) == "Medium"


def test_unmapped_vendor_is_not_assessed_and_skips_matrix():
    vendor = {"vendor_name": "X", "is_mapped": 0, "data_sensitivity": "regulated"}
    assert scoring.final_tier(vendor, cves_for("T4")) == scoring.NOT_ASSESSED
    assessment = scoring.assess(vendor, cves_for("T4"))
    assert assessment["tier"] == "Not Assessed"
    assert assessment["threat_band"] is None
    assert assessment["exposure_band"] is None


def test_only_unscored_cves_lands_in_t1_without_crashing():
    cves = [{"is_kev": 0, "cvss_score": None}, {"is_kev": 0, "cvss_score": None}]
    assert scoring.threat_band(cves) == "T1"
    assert scoring.max_cvss(cves) is None
    vendor = vendor_for("E2")
    assert scoring.final_tier(vendor, cves) == EXPECTED[("T1", "E2")]


def test_three_high_cves_reach_t3():
    cves = [{"is_kev": 0, "cvss_score": s} for s in (7.0, 7.2, 8.9)]
    assert scoring.threat_band(cves) == "T3"
