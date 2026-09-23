"""Portfolio reporting: CSV data export and a formatted PDF report.

Every export carries the scope disclaimer verbatim (a locked integrity rule), and
honest-data rules hold on the way out: an unscored vendor exports a blank Max
CVSS (never 0.0) and keeps its "Not Assessed" tier (never "Low").

WeasyPrint (HTML->PDF) needs GTK/Pango system libraries that exist in the Docker
image but not on a bare dev box or CI, so it is imported lazily inside
:func:`portfolio_pdf` only; the CSV and the HTML body are pure and portable.
"""
from __future__ import annotations

import csv
import html
import io
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from core.constants import SCOPE_DISCLAIMER

from ..models import Organization
from . import scoring_service, vendor_service

# CSV columns: (header, row-key). The first header is "Vendor" (used as an anchor).
_COLUMNS: list[tuple[str, str]] = [
    ("Vendor", "name"),
    ("CPE prefix", "cpe_prefix"),
    ("Tier", "tier"),
    ("Threat", "threat_band"),
    ("Exposure", "exposure_band"),
    ("Max CVSS", "max_cvss"),
    ("CVEs", "cve_count"),
    ("KEV", "kev_count"),
    ("Mapped", "mapped"),
    ("Data sensitivity", "data_sensitivity"),
    ("Criticality", "business_criticality"),
    ("Annual contract value", "annual_contract_value"),
    ("Renewal date", "contract_renewal_date"),
    ("Last sync", "last_synced_at"),
]


def _cell(value: object) -> str:
    """Render a value for CSV: None -> "" (never 0.0), bools -> yes/no."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def vendor_rows(db: Session, org_id: int) -> list[dict]:
    """One assessment row per vendor, honest-data preserved."""
    rows: list[dict] = []
    for v in vendor_service.list_vendors(db, org_id):
        a = scoring_service.assess_vendor(db, v)
        rows.append(
            {
                "name": v.name,
                "cpe_prefix": v.cpe_prefix,
                "tier": a["tier"],
                "threat_band": a["threat_band"],
                "exposure_band": a["exposure_band"],
                "max_cvss": a["max_cvss"],  # None when unscored -> blank
                "cve_count": a["cve_count"],
                "kev_count": a["kev_count"],
                "mapped": v.is_mapped,
                "data_sensitivity": v.data_sensitivity,
                "business_criticality": v.business_criticality,
                "annual_contract_value": v.annual_contract_value,
                "contract_renewal_date": (
                    v.contract_renewal_date.isoformat() if v.contract_renewal_date else None
                ),
                "last_synced_at": (
                    v.last_synced_at.isoformat(timespec="minutes") if v.last_synced_at else None
                ),
            }
        )
    return rows


def portfolio_summary(rows: list[dict]) -> dict:
    tier_counts: dict[str, int] = {}
    for r in rows:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1
    return {
        "total": len(rows),
        "mapped": sum(1 for r in rows if r["mapped"]),
        "kev_exposed": sum(1 for r in rows if r["kev_count"]),
        "tier_counts": tier_counts,
    }


def _generated_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def filename(org: Organization, ext: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"vendor-risk-{org.slug}-{stamp}.{ext}"


# --------------------------------------------------------------------------- #
# CSV                                                                          #
# --------------------------------------------------------------------------- #
def portfolio_csv(db: Session, org_id: int, org: Organization) -> str:
    rows = vendor_rows(db, org_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Metadata + disclaimer as single quoted cells so commas never break parsing.
    writer.writerow(["Vendor Risk portfolio export"])
    writer.writerow(["Organization", org.name])
    writer.writerow(["Generated", _generated_at()])
    writer.writerow([])
    writer.writerow(["Scope disclaimer", SCOPE_DISCLAIMER])
    writer.writerow([])
    writer.writerow([h for h, _ in _COLUMNS])
    for r in rows:
        writer.writerow([_cell(r[key]) for _, key in _COLUMNS])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# PDF (HTML body is pure; the render step lazy-imports WeasyPrint)             #
# --------------------------------------------------------------------------- #
def _tier_class(tier: str) -> str:
    return "tier-" + tier.lower().replace(" ", "-")


def build_portfolio_html(db: Session, org_id: int, org: Organization) -> str:
    rows = vendor_rows(db, org_id)
    summary = portfolio_summary(rows)
    esc = html.escape

    def td(value: object, *, cls: str = "") -> str:
        text = _cell(value) if not isinstance(value, str) else value
        return f'<td class="{cls}">{esc(text) if text else "—"}</td>'

    body_rows = "".join(
        "<tr>"
        + f'<td class="name">{esc(r["name"])}</td>'
        + f'<td><span class="tier {_tier_class(r["tier"])}">{esc(r["tier"])}</span></td>'
        + td(r["max_cvss"], cls="num")
        + td(r["cve_count"], cls="num")
        + td(r["kev_count"], cls="num")
        + f'<td class="mono">{esc(r["cpe_prefix"] or "—")}</td>'
        + td(r["last_synced_at"])
        + "</tr>"
        for r in rows
    )

    tier_chips = "".join(
        f'<span class="chip"><b>{count}</b> {esc(tier)}</span>'
        for tier, count in sorted(summary["tier_counts"].items())
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 20mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
          color: #1a2230; font-size: 10.5px; line-height: 1.45; }}
  .head {{ border-bottom: 2px solid #385ea3; padding-bottom: 10px; margin-bottom: 14px; }}
  .head h1 {{ margin: 0; font-size: 17px; color: #26437a; }}
  .head .sub {{ color: #5b6675; margin-top: 2px; }}
  .summary {{ display: flex; gap: 10px; margin: 12px 0; flex-wrap: wrap; }}
  .stat {{ border: 1px solid #d9e0ea; border-radius: 6px; padding: 8px 12px; min-width: 92px; }}
  .stat .n {{ font-size: 18px; font-weight: 600; color: #26437a; }}
  .stat .l {{ color: #5b6675; font-size: 9px; text-transform: uppercase; letter-spacing: .04em; }}
  .chips {{ margin: 6px 0 14px; }}
  .chip {{ display: inline-block; border: 1px solid #d9e0ea; border-radius: 20px;
           padding: 2px 10px; margin-right: 6px; font-size: 9.5px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: .04em;
        color: #5b6675; border-bottom: 1px solid #c9d2e0; padding: 5px 6px; }}
  td {{ padding: 5px 6px; border-bottom: 1px solid #eef1f6; vertical-align: top; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.name {{ font-weight: 600; }}
  .mono {{ font-family: Consolas, Menlo, monospace; font-size: 9px; color: #5b6675; }}
  .tier {{ font-weight: 600; }}
  .tier-critical {{ color: #b3261e; }} .tier-high {{ color: #c05621; }}
  .tier-medium {{ color: #8a6d00; }} .tier-low {{ color: #2f7a4d; }}
  .tier-not-assessed {{ color: #5b6675; }}
  .disclaimer {{ margin-top: 18px; padding: 10px 12px; border: 1px solid #d9e0ea;
                 border-radius: 6px; background: #f6f8fb; color: #3a4453; font-size: 9.5px; }}
  .disclaimer b {{ color: #26437a; }}
</style></head><body>
  <div class="head">
    <h1>Vendor Risk — Portfolio Report</h1>
    <div class="sub">{esc(org.name)} &middot; generated {esc(_generated_at())}</div>
  </div>
  <div class="summary">
    <div class="stat"><div class="n">{summary["total"]}</div><div class="l">Vendors</div></div>
    <div class="stat"><div class="n">{summary["mapped"]}</div><div class="l">Mapped</div></div>
    <div class="stat"><div class="n">{summary["kev_exposed"]}</div><div class="l">KEV-exposed</div></div>
  </div>
  <div class="chips">{tier_chips}</div>
  <table>
    <thead><tr>
      <th>Vendor</th><th>Tier</th><th>Max CVSS</th><th>CVEs</th><th>KEV</th>
      <th>CPE prefix</th><th>Last sync</th>
    </tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
  <div class="disclaimer"><b>Scope.</b> {html.escape(SCOPE_DISCLAIMER, quote=False)}</div>
</body></html>"""


def portfolio_pdf(db: Session, org_id: int, org: Organization) -> bytes:
    """Render the portfolio report to PDF bytes. Requires WeasyPrint at runtime."""
    document = build_portfolio_html(db, org_id, org)
    from weasyprint import HTML  # lazy: needs GTK/Pango (present in the Docker image)

    return HTML(string=document).write_pdf()
