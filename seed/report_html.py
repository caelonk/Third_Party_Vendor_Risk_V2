"""Render a self-contained HTML snapshot + watchlist CSV for the dev seed.

Ported from the demo's ``report.py``. This is a **developer** artifact, not the
product UI (the product UI is the React SPA). It stays useful for eyeballing a
local seed run offline. The scope disclaimer, watchlist rule, and watchlist
columns are sourced from :mod:`core.constants` so there is a single source of
truth; the pastel ``TIER_STYLE`` tints here are the demo's reference point only —
the product redraws them into professional light/dark severity tokens.

Honest-data rules visible here: missing CVSS shows as "Unscored" (never 0.0);
unmapped/failed vendors show as "Not Assessed" in a distinct style; and the
footer carries the scope disclaimer verbatim.
"""
from __future__ import annotations

import csv
import html
from datetime import date
from pathlib import Path

from core import scoring
from core.constants import (
    SCOPE_DISCLAIMER,
    WATCHLIST_COLUMNS,
    WATCHLIST_WINDOW_DAYS,
)

from . import sqlite_store as db

# Reference date for the deterministic seed: renewal windows are measured from
# here so a seeded run always has a populated watchlist. Shared with the
# synthetic business-data generator in pipeline.py.
REFERENCE_DATE = date(2026, 8, 1)

BUSINESS_DATA_NOTICE = (
    "Vendor names and all CVE / KEV vulnerability data are REAL, from the public "
    "NVD 2.0 API. Contract values, data sensitivity, business criticality, and "
    "renewal dates are SYNTHETIC — fabricated for this dev seed, not real business data."
)

# tier -> (background tint, text color) for badges and heatmap cells.
TIER_STYLE = {
    "Critical":     ("#f8d0d4", "#7d1620"),
    "High":         ("#ffd9bd", "#7a3400"),
    "Medium":       ("#fdeeba", "#6b4e00"),
    "Low":          ("#cfe8d8", "#0f5132"),
    "Not Assessed": ("#e0e1e2", "#3f4448"),
}
EMPTY_CELL = ("#f4f5f6", "#9aa0a6")


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_cvss(max_cvss, cve_count) -> str:
    if max_cvss is not None:
        return f"{max_cvss:.1f}"
    return "Unscored" if cve_count > 0 else "—"


def _tier_badge(tier: str) -> str:
    bg, fg = TIER_STYLE.get(tier, EMPTY_CELL)
    return f'<span class="badge" style="background:{bg};color:{fg}">{_esc(tier)}</span>'


def _days_until(iso_date: str | None, reference: date) -> int | None:
    if not iso_date:
        return None
    try:
        return (date.fromisoformat(iso_date) - reference).days
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Data assembly                                                                #
# --------------------------------------------------------------------------- #
def _build_assessments(conn) -> list[dict]:
    assessments = []
    for vendor in db.get_all_vendors(conn):
        cves = db.get_cves_for_vendor(conn, vendor["vendor_id"])
        assessments.append(scoring.assess(vendor, cves))
    return assessments


def _watchlist_rows(assessments: list[dict], reference: date) -> list[dict]:
    rows = []
    for a in assessments:
        if a["tier"] not in ("High", "Critical"):
            continue
        days = _days_until(a["contract_renewal_date"], reference)
        if days is None or not (0 <= days <= WATCHLIST_WINDOW_DAYS):
            continue
        rows.append({**a, "days_until_renewal": days})
    rows.sort(key=lambda r: r["contract_renewal_date"])
    return rows


# --------------------------------------------------------------------------- #
# CSV                                                                          #
# --------------------------------------------------------------------------- #
def _write_watchlist_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(WATCHLIST_COLUMNS))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in WATCHLIST_COLUMNS})


# --------------------------------------------------------------------------- #
# HTML sections                                                                #
# --------------------------------------------------------------------------- #
def _section_watchlist(rows: list[dict]) -> str:
    if not rows:
        body = ('<p class="muted">No High/Critical vendors have a contract renewal in the '
                f'next {WATCHLIST_WINDOW_DAYS} days.</p>')
    else:
        trs = []
        for r in rows:
            trs.append(
                "<tr>"
                f"<td>{_esc(r['vendor_name'])}</td>"
                f"<td>{_tier_badge(r['tier'])}</td>"
                f"<td>{_esc(r['contract_renewal_date'])}</td>"
                f"<td class='num'>{r['days_until_renewal']}</td>"
                f"<td class='num'>{_fmt_cvss(r['max_cvss'], r['cve_count'])}</td>"
                f"<td class='num'>{r['kev_count']}</td>"
                "</tr>"
            )
        body = (
            '<table><thead><tr>'
            '<th>Vendor</th><th>Tier</th><th>Renewal</th><th class="num">Days</th>'
            '<th class="num">Max CVSS</th><th class="num">KEV</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table>'
        )
    return (
        '<section><h2>1 &middot; Renewal Watchlist</h2>'
        f'<p class="muted">High/Critical vendors with a contract renewal in the next '
        f'{WATCHLIST_WINDOW_DAYS} days &mdash; the decisions with a clock on them. '
        'Also written to <code>output/watchlist.csv</code>.</p>'
        f'{body}</section>'
    )


def _section_heatmap(assessments: list[dict]) -> str:
    cells: dict[tuple[str, str], list[str]] = {}
    for a in assessments:
        if not a["is_mapped"]:
            continue
        cells.setdefault((a["threat_band"], a["exposure_band"]), []).append(a["vendor_name"])

    header = ('<tr><th></th>'
              + "".join(f"<th>{e}</th>" for e in scoring.EXPOSURE_BANDS)
              + "</tr>")
    body_rows = []
    for t in reversed(scoring.THREAT_BANDS):  # T4 at top
        tds = [f'<th class="rowhead">{t}</th>']
        for e in scoring.EXPOSURE_BANDS:
            tier = scoring.MATRIX[(t, e)]
            names = cells.get((t, e), [])
            bg, fg = TIER_STYLE[tier] if names else EMPTY_CELL
            title = _esc(", ".join(names)) if names else "no vendors"
            count = f'<span class="cell-count">{len(names)}</span>' if names else '<span class="cell-zero">0</span>'
            tds.append(
                f'<td class="cell" style="background:{bg};color:{fg}" title="{title}">'
                f'{count}<span class="cell-tier">{tier}</span></td>'
            )
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    return (
        '<section><h2>2 &middot; Risk Matrix Heatmap</h2>'
        '<p class="muted">Threat band (rows, T4 highest) &times; exposure band (columns, '
        'E4 highest). Cell number = vendors in that cell; hover for names. Tint follows the '
        'final tier, not a formula.</p>'
        '<table class="heatmap"><thead>' + header + '</thead><tbody>'
        + "".join(body_rows) + '</tbody></table></section>'
    )


def _section_vendor_detail(assessments: list[dict]) -> str:
    mapped = [a for a in assessments if a["is_mapped"]]
    unmapped = [a for a in assessments if not a["is_mapped"]]
    mapped.sort(key=lambda a: (-scoring.TIER_ORDER.index(a["tier"]), a["vendor_name"]))
    unmapped.sort(key=lambda a: a["vendor_name"])

    def row(a: dict) -> str:
        return (
            "<tr>"
            f"<td>{_esc(a['vendor_name'])}</td>"
            f"<td>{_tier_badge(a['tier'])}</td>"
            f"<td class='num'>{_esc(a['threat_band'])}</td>"
            f"<td class='num'>{_esc(a['exposure_band'])}</td>"
            f"<td class='num'>{_fmt_cvss(a['max_cvss'], a['cve_count'])}</td>"
            f"<td class='num'>{a['cve_count']}</td>"
            f"<td class='num'>{a['kev_count']}</td>"
            f"<td>{_esc(a['contract_renewal_date'])}</td>"
            "</tr>"
        )

    head = ('<table><thead><tr><th>Vendor</th><th>Tier</th><th class="num">Threat</th>'
            '<th class="num">Exposure</th><th class="num">Max CVSS</th>'
            '<th class="num">CVEs</th><th class="num">KEV</th><th>Renewal</th>'
            '</tr></thead><tbody>')
    mapped_table = head + "".join(row(a) for a in mapped) + "</tbody></table>"

    parts = ['<section><h2>3 &middot; Vendor Detail</h2>', mapped_table]
    if unmapped:
        rows = "".join(
            f"<tr class='na'><td>{_esc(a['vendor_name'])}</td>"
            f"<td>{_tier_badge('Not Assessed')}</td>"
            f"<td colspan='6' class='muted'>No usable data &mdash; not scored. "
            "Absence of data is not evidence of low risk.</td></tr>"
            for a in unmapped
        )
        parts.append(
            '<h3>Not Assessed <span class="muted">(unmapped or failed fetch &mdash; '
            'never treated as &ldquo;Low&rdquo;)</span></h3>'
            '<table class="na-table"><tbody>' + rows + '</tbody></table>'
        )
    parts.append("</section>")
    return "".join(parts)


def _section_data_health(conn, run: dict | None, assessments: list[dict]) -> str:
    total_cves = db.count_rows(conn, "vulnerabilities")
    unscored = db.count_unscored(conn)
    methods: dict[str, int] = {}
    for a in assessments:
        if a["is_mapped"]:
            methods[a["match_method"] or "unknown"] = methods.get(a["match_method"] or "unknown", 0) + 1
    not_assessed = sum(1 for a in assessments if not a["is_mapped"])

    run = run or {}
    method_txt = ", ".join(f"{k}: {v}" for k, v in sorted(methods.items())) or "—"
    items = [
        ("Run completed", run.get("completed_at") or run.get("started_at")),
        ("Mode", run.get("mode")),
        ("Status", run.get("status")),
        ("Vendors succeeded / attempted",
         f"{run.get('vendors_succeeded')} / {run.get('vendors_attempted')}"),
        ("CVEs stored", total_cves),
        ("Unscored CVEs", f"{unscored} (shown as “Unscored”, never 0.0)"),
        ("Not Assessed vendors", not_assessed),
        ("Match method breakdown", method_txt),
    ]
    if run.get("error_detail"):
        items.append(("Errors", run.get("error_detail")))
    rows = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in items
    )
    return ('<section><h2>4 &middot; Data Health</h2>'
            f'<table class="kv"><tbody>{rows}</tbody></table></section>')


# --------------------------------------------------------------------------- #
# Page                                                                         #
# --------------------------------------------------------------------------- #
STYLE = """
:root { --fg:#1c1f23; --muted:#6b7178; --line:#e3e6e9; --bg:#ffffff; --panel:#fbfcfd; }
* { box-sizing: border-box; }
body { margin:0; color:var(--fg); background:var(--bg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height:1.5; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 32px 24px 64px; }
header.top h1 { margin:0 0 4px; font-size:1.6rem; }
header.top .sub { color:var(--muted); margin:0; }
.banner { padding:12px 16px; border-radius:8px; font-weight:600; margin:18px 0; }
.banner.business { background:#fff3cd; color:#6b4e00; border:1px solid #f2d98a; font-weight:500; }
section { margin:34px 0; }
h2 { font-size:1.15rem; border-bottom:2px solid var(--line); padding-bottom:6px; }
h3 { font-size:1rem; margin-top:22px; }
p.muted, .muted { color:var(--muted); }
table { border-collapse:collapse; width:100%; margin-top:12px; font-size:0.92rem; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
thead th { font-size:0.78rem; text-transform:uppercase; letter-spacing:0.03em; color:var(--muted); }
td.num, th.num { text-align:right; font-variant-numeric: tabular-nums; }
.badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:0.8rem; font-weight:600; }
table.kv th { width:280px; color:var(--fg); font-weight:600; }
table.heatmap { table-layout:fixed; }
table.heatmap th.rowhead { text-align:center; color:var(--muted); font-weight:600; width:52px; }
table.heatmap td.cell { text-align:center; border:3px solid var(--bg); border-radius:6px;
  padding:14px 6px; }
.cell-count { display:block; font-size:1.4rem; font-weight:700; }
.cell-zero { display:block; font-size:1.1rem; font-weight:600; }
.cell-tier { display:block; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.03em; opacity:0.85; }
.na-table td { background:#f6f7f8; }
tr.na td { color:#3f4448; }
code { background:#f0f2f4; padding:1px 5px; border-radius:4px; font-size:0.88em; }
footer { margin-top:48px; padding-top:18px; border-top:2px solid var(--line); color:var(--muted);
  font-size:0.88rem; }
footer .disclaimer { background:var(--panel); border-left:4px solid #90a4ae; padding:12px 16px;
  border-radius:4px; color:var(--fg); }
"""


def render_html(conn, run: dict | None, assessments: list[dict], *, reference: date) -> str:
    watchlist = _watchlist_rows(assessments, reference)
    generated = (run or {}).get("completed_at") or (run or {}).get("started_at") or ""
    mode = (run or {}).get("mode")
    if mode == "offline":
        data_line = "Vulnerability data is real NVD data, replayed from saved fixtures (public, no API key)."
    else:
        data_line = "Vulnerability data is real, pulled live from the NVD 2.0 API (public)."
    return f"""<div class="wrap">
<header class="top">
  <h1>Vendor Risk &mdash; dev seed snapshot</h1>
  <p class="sub">Published-vulnerability exposure across seeded vendors &middot; generated {_esc(generated)}</p>
</header>
<div class="banner business">{_esc(BUSINESS_DATA_NOTICE)}</div>
{_section_watchlist(watchlist)}
{_section_heatmap(assessments)}
{_section_vendor_detail(assessments)}
{_section_data_health(conn, run, assessments)}
<footer>
  <p class="disclaimer">{html.escape(SCOPE_DISCLAIMER, quote=False)}</p>
  <p>Developer seed snapshot with synthetic business data. {data_line}</p>
</footer>
</div>"""


def render(conn, *, run: dict | None, output_dir, reference: date | None = None) -> dict:
    """Write dashboard.html + watchlist.csv. Returns the paths written."""
    reference = reference or REFERENCE_DATE
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assessments = _build_assessments(conn)
    watchlist = _watchlist_rows(assessments, reference)

    html_path = output_dir / "dashboard.html"
    csv_path = output_dir / "watchlist.csv"
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Vendor Risk — dev seed</title><style>" + STYLE + "</style></head>"
        "<body>" + render_html(conn, run, assessments, reference=reference)
        + "</body></html>"
    )
    html_path.write_text(page, encoding="utf-8")
    _write_watchlist_csv(csv_path, watchlist)
    return {"dashboard": html_path, "watchlist": csv_path, "watchlist_count": len(watchlist)}
