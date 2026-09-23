"""Portfolio export: CSV + PDF report. The scope disclaimer must appear verbatim
in every export (a locked integrity rule), and honest-data rules hold (an
unscored vendor exports blank, never 0.0)."""
import csv
import io

import pytest

from app.models import Organization, Vendor, VendorVulnerability, Vulnerability
from app.services import export_service
from core.constants import SCOPE_DISCLAIMER

API = "/api/v1"


def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def _add_vendor(db, oid, name, *, mapped=False):
    v = Vendor(org_id=oid, name=name, is_mapped=mapped, cpe_prefix="cpe:2.3:a:x:y" if mapped else None)
    db.add(v)
    db.commit()
    return v.id


def _link_cve(db, vendor_id, cve_id, *, cvss, kev=False):
    if db.get(Vulnerability, cve_id) is None:
        db.add(Vulnerability(cve_id=cve_id, cvss_score=cvss, is_kev=kev))
        db.flush()  # parent before the association (FK enforced in tests)
    db.add(VendorVulnerability(vendor_id=vendor_id, cve_id=cve_id))
    db.commit()


def _seed(api):
    client, _ = api.register("exp@acme.io", org_name="Acme")
    oid = _org_id(client)
    with api.db() as db:
        _add_vendor(db, oid, "Alpha Unmapped", mapped=False)  # Not Assessed
        beta = _add_vendor(db, oid, "Beta Scored", mapped=True)
        _link_cve(db, beta, "CVE-2024-9001", cvss=9.1, kev=True)
        _link_cve(db, beta, "CVE-2024-9002", cvss=5.0, kev=False)
    return client, oid


# --------------------------------------------------------------------------- #
# CSV                                                                          #
# --------------------------------------------------------------------------- #
def _disclaimer_cell(rows: list[list[str]]) -> str | None:
    for r in rows:
        if len(r) >= 2 and r[0] == "Scope disclaimer":
            return r[1]
    return None


def test_csv_includes_disclaimer_verbatim_and_rows(api):
    client, oid = _seed(api)
    with api.db() as db:
        text = export_service.portfolio_csv(db, oid, db.get(Organization, oid))

    rows = list(csv.reader(io.StringIO(text)))
    # Verbatim in the decoded cell (CSV quotes the commas/quotes at the file level).
    assert _disclaimer_cell(rows) == SCOPE_DISCLAIMER

    header = next(r for r in rows if r and r[0] == "Vendor")
    data = rows[rows.index(header) + 1 :]
    by_name = {r[0]: r for r in data if r}
    cvss_col = header.index("Max CVSS")

    assert by_name["Alpha Unmapped"][header.index("Tier")] == "Not Assessed"
    assert by_name["Alpha Unmapped"][cvss_col] == ""  # unscored -> blank, never 0.0
    assert by_name["Beta Scored"][cvss_col] == "9.1"
    assert by_name["Beta Scored"][header.index("KEV")] == "1"


# --------------------------------------------------------------------------- #
# Portfolio summary + HTML (PDF body, testable without WeasyPrint)             #
# --------------------------------------------------------------------------- #
def test_portfolio_summary_counts(api):
    client, oid = _seed(api)
    with api.db() as db:
        rows = export_service.vendor_rows(db, oid)
    summary = export_service.portfolio_summary(rows)
    assert summary["total"] == 2
    assert summary["mapped"] == 1
    assert summary["kev_exposed"] == 1
    assert summary["tier_counts"]["Not Assessed"] == 1


def test_html_report_contains_disclaimer_and_vendors(api):
    client, oid = _seed(api)
    with api.db() as db:
        html = export_service.build_portfolio_html(db, oid, db.get(Organization, oid))
    assert SCOPE_DISCLAIMER in html
    assert "Alpha Unmapped" in html and "Beta Scored" in html
    assert "Acme" in html


# --------------------------------------------------------------------------- #
# API endpoints                                                               #
# --------------------------------------------------------------------------- #
def test_csv_endpoint_downloads_attachment(api):
    client, oid = _seed(api)
    res = client.get(f"{API}/orgs/{oid}/export/vendors.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert ".csv" in res.headers["content-disposition"]
    assert _disclaimer_cell(list(csv.reader(io.StringIO(res.text)))) == SCOPE_DISCLAIMER


def test_export_non_member_gets_404(api):
    client, oid = _seed(api)
    outsider, _ = api.register("exp-out@acme.io")
    assert outsider.get(f"{API}/orgs/{oid}/export/vendors.csv").status_code == 404


def _weasyprint_ok() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _weasyprint_ok(), reason="WeasyPrint/GTK not available")
def test_pdf_endpoint_returns_pdf(api):
    client, oid = _seed(api)
    res = client.get(f"{API}/orgs/{oid}/export/portfolio.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:5] == b"%PDF-"
