"""Parser unit tests. No network — hand-crafted fixtures only."""
import json
from pathlib import Path

from core import parser

FIXTURE = Path(__file__).parent / "fixtures" / "parser" / "metrics_cases.json"


def _records() -> dict[str, dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {r["cve_id"]: r for r in parser.parse_response(payload)}


def test_extracts_v31_score():
    r = _records()["CVE-T-0031"]
    assert r["cvss_score"] == 7.5
    assert r["cvss_version"] == "3.1"
    assert r["cvss_severity"] == "HIGH"


def test_prefers_v40_over_v31_when_both_present():
    r = _records()["CVE-T-4031"]
    assert r["cvss_score"] == 9.1
    assert r["cvss_version"] == "4.0"


def test_falls_back_to_v2_when_only_metric():
    r = _records()["CVE-T-0020"]
    assert r["cvss_score"] == 6.8
    assert r["cvss_version"] == "2.0"
    # CVSS v2 keeps baseSeverity at the metric level, not in cvssData.
    assert r["cvss_severity"] == "MEDIUM"


def test_empty_metrics_returns_none_not_zero():
    r = _records()["CVE-T-EMPTYMETRIC"]
    assert r["cvss_score"] is None
    assert r["cvss_score"] != 0.0
    assert r["cvss_version"] is None


def test_absent_metrics_returns_none():
    r = _records()["CVE-T-NOMETRIC"]
    assert r["cvss_score"] is None
    assert r["cvss_version"] is None


def test_extract_cvss_handles_none_and_empty():
    assert parser.extract_cvss(None) == (None, None, None)
    assert parser.extract_cvss({}) == (None, None, None)


def test_kev_present_sets_flag_and_dates():
    r = _records()["CVE-T-KEV"]
    assert r["is_kev"] == 1
    assert r["kev_date_added"] == "2023-05-01"
    assert r["kev_due_date"] == "2023-05-22"


def test_kev_absent_sets_false():
    r = _records()["CVE-T-NOKEV"]
    assert r["is_kev"] == 0
    assert r["kev_date_added"] is None
    assert r["kev_due_date"] is None


def test_sparse_record_does_not_raise():
    # Missing descriptions, published, and metrics all at once.
    r = _records()["CVE-T-SPARSE"]
    assert r["cve_id"] == "CVE-T-SPARSE"
    assert r["description"] is None
    assert r["published_date"] is None
    assert r["vuln_status"] is None
    assert r["cvss_score"] is None
    assert r["is_kev"] == 0
