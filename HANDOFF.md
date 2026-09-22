# Project Handoff / Kickoff — Vendor Risk Platform

**Purpose of this file.** This is a self-contained kickoff for building the full
Vendor Risk product in a **new repository and a new chat**. A fresh Claude session
can be given this file as its starting context and have everything it needs: the
mission, the locked decisions, the reusable core from the original demo (embedded
below so you do not need the old repo open), the design requirements, the roadmap,
and concrete first steps.

There is a companion file, `PLAN.md`, with the full long-form plan. Bring it along
if you can, but this handoff alone is enough to start.

---

## 0. First actions for the new session

1. Confirm the target: a brand-new repo for the full application (not the demo repo).
2. **Verify GitHub write access early.** In the demo repo, pushes failed with HTTP
   403 because the Claude GitHub App lacked write access — do not let that bite you
   again. Before writing code, confirm the Claude GitHub App has **write** access to
   the new repo (install/select at https://github.com/apps/claude/installations/select_target),
   or attach it for push in-session and do a trivial test commit/push.
3. Pull in the reusable core (Section 2): either attach/clone the source demo repo
   `https://github.com/caelonk/vendor-risk-dashboard` (public) and copy the modules,
   or reimplement them from the embedded specs below.
4. Start on **Phase 0** (Section 7), then Phase 1.
5. Optional: the "superpowers" plugin (obra) gives a brainstorm/plan/execute
   workflow. It was not available in the demo's remote session; if you want it,
   install it in a local Claude Code session first:
   `/plugin install superpowers@claude-plugins-official` (then start a fresh session).

---

## 1. Mission

Turn a single-tenant vulnerability-scoring demo into a full **multi-tenant SaaS**:
teams sign in, add the real vendors they depend on, and get continuous
published-vulnerability risk scoring, automated monitoring and alerting,
reporting/export, and a customizable dashboard. Keep the demo's honest-data
stance (never turn missing data into reassuring data). Strip all demo/synthetic
framing.

---

## 2. Origin and the reusable core (important for a new repo)

The original demo (`caelonk/vendor-risk-dashboard`) is a Python 3.10+ batch CLI
pipeline (only runtime dep: `requests`; stdlib `sqlite3`) that pulls real CVE +
CISA KEV data from the NVD 2.0 API, scores 12 hardcoded vendors, and writes a
static HTML report. It is **not** a web app, but its domain core is clean, pure,
and well-tested (38 tests) and should be reused rather than rewritten.

**Port these (from the source repo, or reimplement from the specs below):**

### 2a. Risk model (the heart — pure, no I/O; port verbatim)

Threat band from a vendor's CVEs: `T4` if any KEV; else `T3` if max CVSS >= 9.0 or
at least three CVEs >= 7.0; else `T2` if max CVSS >= 7.0; else `T1`. Unscored
(NULL) CVSS never counts toward thresholds.

Exposure band from business context (highest wins): `E4` regulated or ACV >= 500k;
`E3` confidential or ACV >= 100k or criticality high; `E2` ACV >= 25k; `E1` otherwise.

Final tier is a **literal lookup matrix, not arithmetic** (kept editable):

|        | E1 | E2 | E3 | E4 |
|--------|----|----|----|----|
| **T4** | High | High | Critical | Critical |
| **T3** | Medium | High | High | Critical |
| **T2** | Low | Medium | Medium | High |
| **T1** | Low | Low | Low | Medium |

Reference implementation (from `src/scoring.py`):

```python
MATRIX = {
  ("T4","E1"):"High",   ("T4","E2"):"High",   ("T4","E3"):"Critical", ("T4","E4"):"Critical",
  ("T3","E1"):"Medium", ("T3","E2"):"High",   ("T3","E3"):"High",     ("T3","E4"):"Critical",
  ("T2","E1"):"Low",    ("T2","E2"):"Medium", ("T2","E3"):"Medium",   ("T2","E4"):"High",
  ("T1","E1"):"Low",    ("T1","E2"):"Low",    ("T1","E3"):"Low",      ("T1","E4"):"Medium",
}

def threat_band(cves):
    if any(c.get("is_kev") for c in cves): return "T4"
    scores = [c["cvss_score"] for c in cves if c.get("cvss_score") is not None]  # NULL != 0
    top = max(scores) if scores else None
    high = sum(1 for s in scores if s >= 7.0)
    if (top is not None and top >= 9.0) or high >= 3: return "T3"
    if top is not None and top >= 7.0: return "T2"
    return "T1"

def exposure_band(v):
    acv = v.get("annual_contract_value") or 0
    sens = (v.get("data_sensitivity") or "").lower()
    crit = (v.get("business_criticality") or "").lower()
    if sens == "regulated" or acv >= 500_000: return "E4"
    if sens == "confidential" or acv >= 100_000 or crit == "high": return "E3"
    if acv >= 25_000: return "E2"
    return "E1"

# Unmapped/failed vendors -> "Not Assessed"; never enter the matrix, never shown as "Low".
```

**Design rationale to preserve:** a KEV floors a vendor at High (whole T4 row is
High/Critical) but is deliberately NOT forced to Critical — that would collapse the
exposure axis. The tool measures published vulnerabilities in vendor products, not
confirmed compromise.

### 2b. Data model (SQLite schema to port to Postgres)

From `src/db.py` (semantics to carry over; reimplement with SQLAlchemy + Alembic):

```sql
vendors(vendor_id PK, vendor_name UNIQUE, annual_contract_value REAL,
        data_sensitivity, business_criticality, contract_renewal_date,
        is_mapped INT, match_method)  -- 'virtual_match' | 'keyword'
vulnerabilities(cve_id PK, cvss_score REAL NULL,  -- NEVER coalesced to 0.0
        cvss_version, cvss_severity, is_kev INT, kev_date_added, kev_due_date,
        published_date, vuln_status, description)
vendor_vulnerabilities(vendor_id FK, cve_id FK, PRIMARY KEY(vendor_id, cve_id))
ingest_runs(run_id PK, started_at, completed_at, status, mode,
        vendors_attempted, vendors_succeeded, cves_upserted, error_detail)
```

All writes are idempotent `INSERT ... ON CONFLICT ... DO UPDATE`. **Never
bulk-DELETE before an ingest**: a vendor whose fetch fails keeps its prior good
rows (integrity rule). Carry these into the new `sync_service`.

### 2c. NVD client (port and lift the demo caps)

`src/nvd_client.py` is a synchronous `requests` client with pagination, backoff on
403/429/503, and rate-limit pacing. Demo caps to **lift** in the product: 119-day
window, 3-page limit, 7s keyless pacing, no API key. Add an `api_key` parameter and
make the caps arguments; switch scheduled sync to incremental via NVD's
`lastModStartDate` watermark. Vendors map to NVD via `virtualMatchString` at the
CPE vendor-prefix level (e.g. `cpe:2.3:a:atlassian`), falling back to keyword search.

### 2d. Constants and integrity rules to preserve

- Scope disclaimer (verbatim, in the app footer and every export): "This tool
  measures published vulnerabilities in vendor products. It does not measure
  whether a vendor has been breached, the vendor's internal security posture, or
  whether this organization is actually exposed. A high score means 'investigate,'
  not 'compromised.'"
- "Unscored" is never 0.0; "Not Assessed" is never "Low".
- Watchlist rule: High/Critical vendors whose contract renews within 90 days.
- The demo's `TIER_STYLE` pastel tints are the reference point ONLY — they get
  redrawn into the corporate-minimalist severity scale (Section 6).

**Reuse map:** `src/scoring.py` (verbatim) and `src/parser.py` (verbatim) into a
`core/` package; `src/nvd_client.py` adapted; `src/db.py` -> SQLAlchemy models;
`src/pipeline.py` `run()`/`ingest()` -> `core/sync.py` + a sync service + Celery
tasks (its synthetic-data generator becomes a dev seed only); `src/report.py` is
replaced by the React UI + a PDF export (but its constants and rules move into
`core/constants.py`, the frontend theme, and the export template).

---

## 3. Locked decisions (do not re-litigate)

| Area | Decision |
|------|----------|
| Backend | FastAPI (Python), reusing the demo's core as a library |
| Frontend | React SPA (TypeScript, Vite) |
| Database | PostgreSQL (SQLite semantics carried over) |
| Tenancy | Organization / team workspaces; users belong to an org (an org can be one user) |
| Auth | JWT in httpOnly cookies; Argon2 passwords; RBAC owner/admin/member/viewer; path-based org scoping |
| Background jobs | Celery + Redis + Celery Beat (worker reuses the synchronous NVD client unchanged) |
| Priority features | Alerts & notifications; scheduled auto-sync + risk trends; reporting & export; smart vendor onboarding (CPE + SBOM) |
| Design language | Corporate minimalism; solid professional palette only (no vibrant, pastel, or muted colors); no emojis |
| Theming | First-class light AND dark mode |
| Home dashboard | Per-user customizable board: add up to 5 chart widgets, reduce to none; each widget fluidly expands and minimizes |

---

## 4. Target architecture (condensed)

React SPA -> FastAPI (JSON API, JWT in httpOnly cookie) -> Postgres (system of
record) + Redis (broker + rate-limit). A Celery worker consumes jobs, imports the
same `core/` package (which reaches NVD / SMTP / Slack), and writes results back.
Celery Beat enqueues a single dispatcher on a cron and holds no per-tenant state.

Key insight: **CVE data is public and identical for every tenant; business
context is per-tenant.** So the vulnerability cache is shared/global (dedup by
CVE), and everything derived from business context is per-org.

---

## 5. Data model additions for the product

- **Global:** `organizations`, `users`, `vulnerabilities` (no org_id; shared cache),
  `cpe_sync_state` (per-CPE-prefix `lastMod` watermark for incremental sync).
- **Per-org:** `memberships` (role), `invitations`, `org_integrations` (encrypted
  NVD key / Slack / SMTP, write-only), `vendors` (FK to org; `cpe_prefix`,
  `match_method`, business fields, `next_sync_at`), `vendor_vulnerabilities`,
  `risk_snapshots` (append-only time series -> trends), `alert_rules`,
  `notifications` (unique `dedup_key`), `sync_runs`, `audit_log`.
- **Per-user:** `user_preferences` — `theme` (light|dark|system) and the home
  dashboard layout (ordered list of at most 5 widgets, each with type, config, and
  size/expanded state). **Enforce the 5-widget max in the service layer, not just UI.**

---

## 6. Design system and dashboard requirements (hard requirements)

These came directly from the product owner and are not negotiable:

- **Corporate minimalism.** A solid, professional palette only: a neutral base
  (white / graphite / slate) with a single restrained accent. **No vibrant colors,
  no pastels, no muted/washed-out colors, no decorative gradients, no emojis.**
  Generous whitespace, strong type hierarchy, thin dividers, tabular numerals.
- **Design tokens + light/dark.** All color as CSS custom-property tokens; a
  `data-theme` attribute switches light/dark. Both themes first-class. Theme
  persists per user (server `user_preferences`) and in `localStorage` for a
  flash-free load; system-aware default plus a light/dark/system toggle.
- **Severity encoding.** Redraw the demo's pastel tier tints into a restrained,
  high-contrast professional severity scale, legible and WCAG-AA in both themes,
  **never relying on hue alone** (always paired with a text label/badge). Use the
  project's data-visualization palette methodology to finalize tokens.
- **Customizable home dashboard.** The home page is a personal, per-user board of
  chart/graph widgets. The user **adds up to 5 and can remove down to none.** Each
  widget **fluidly expands and minimizes** (smooth size/height transitions —
  compact header <-> detailed view) and can be reordered/resized. Suggested widget
  catalog: tier distribution, risk heatmap, KEV exposure, CVE trend over time,
  upcoming renewals/watchlist, top-risk vendors, data-health/last-sync. Suggested
  libraries: react-grid-layout or dnd-kit for the grid; Framer Motion or CSS
  transitions for motion; Recharts for charts; a line-icon set (e.g. lucide-react)
  for icons (never emojis). A clean empty state (0 widgets) offers "add a widget".

---

## 7. Phased roadmap

- **Phase 0 — Harden & refactor.** Create the new repo skeleton; `pyproject.toml`
  (fastapi, uvicorn, sqlalchemy 2, alembic, psycopg3, pydantic-settings, celery,
  redis, argon2-cffi, pyjwt, requests, weasyprint; dev: ruff, mypy, pytest). Bring
  in `core/` (scoring, parser verbatim; nvd_client adapted; sync extracted;
  constants). SQLAlchemy models + first Alembic migration (port upsert + integrity
  semantics). Dockerize (compose: api, worker, beat, postgres, redis). Port the
  demo's tests; add Postgres integration tests.
- **Phase 1 — MVP SaaS.** Auth (JWT cookies), orgs, memberships, RBAC; org-scoped
  vendor CRUD; on-demand sync (system key); the design system + light/dark theming;
  the customizable home dashboard (add/remove up to 5 widgets, fluid expand/minimize,
  saved per user) with an initial widget set (tier distribution, heatmap, watchlist,
  KEV exposure, top-risk vendors); vendor list; vendor detail. React shell + auth.
- **Phase 2 — Automation.** Beat dispatcher + per-org schedule + incremental sync +
  stored per-org NVD key; `risk_snapshots` + trend charts (incl. trend widgets on
  the home board); alert rules + email/Slack notifications.
- **Phase 3 — Reporting & onboarding.** CSV + PDF export + export center + audit log;
  advanced filter/search/sort; name->CPE onboarding + CycloneDX/SPDX SBOM import.
- **Phase 4 — Scale & polish.** Google OAuth/SSO, Stripe billing, rate-limit
  hardening (per-key token buckets), object storage for exports, observability.

---

## 8. Feature designs (condensed)

- **Alerts:** typed `alert_rules` (`new_kev | tier_change | renewal_due`); KEV/tier
  evaluated by diffing the fresh `risk_snapshot` against the prior one; renewal via a
  daily scan. Matches write `notifications` with a unique `dedup_key`
  (`org:vendor:type:cve:date`) to prevent duplicate alerts; dispatch email (SMTP) or
  Slack webhook with retries.
- **Scheduled sync + trends:** per-org cadence -> `next_sync_at`; Beat dispatches due
  CPE prefixes (deduped so a shared prefix is fetched once); incremental `lastMod`
  sync; a global Redis token bucket keyed by API key enforces NVD limits across
  workers; each run appends `risk_snapshots`.
- **Reporting/export:** server-side CSV + PDF via WeasyPrint (reuse the report
  structure, severity tokens, and disclaimer); Celery jobs -> object storage ->
  signed URLs; `audit_log` + `risk_snapshots` back the history.
- **Smart onboarding:** name->CPE probe (`virtualMatchString=cpe:2.3:a:<slug>`),
  candidates ranked by `totalResults` for confirmation; SBOM import (CycloneDX/SPDX)
  -> extract components -> map CPE/PURL -> bulk-create vendors -> trigger backfill.

---

## 9. Current status / carry-over

- The full long-form plan is in **`PLAN.md`** (committed in the demo repo as
  `6dbda5a` on branch `claude/sleepy-franklin-fbbekz`, but **not pushed** — the demo
  repo's Claude GitHub App lacked write access, HTTP 403). Bring `PLAN.md` into the
  new repo; it is the detailed version of this handoff.
- No application code was written yet — planning only. The new session starts fresh
  at Phase 0.
- Watch out for the GitHub write-access issue from the start in the new repo
  (Section 0, step 2).

---

## 10. Guardrails to keep from the demo

- Honest data: "Unscored" never 0.0; "Not Assessed" never "Low"; a partial sync
  keeps prior good rows.
- The scope disclaimer verbatim in the app and every export.
- KEV floors at High, not Critical.
- Remove all demo/synthetic framing: the synthetic business-data generator (keep as
  a dev seed only), "Demo Edition", the portfolio ribbon, the synthetic-data
  banner, the fixed-12-vendor scope, the 119-day/3-page/keyless caps, and all
  emojis (replace with line icons).
