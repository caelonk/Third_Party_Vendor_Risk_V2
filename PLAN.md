# Vendor Risk Dashboard — Product & Engineering Plan

This document is the plan for turning the current Vendor Risk Dashboard demo into a
full, multi-tenant web application: users sign in, track their own real vendors,
and get automated risk monitoring, alerting, reporting, and a customizable
dashboard. It captures the target architecture, data model, feature set, design
system, and a phased delivery roadmap.

It is a living plan, not a contract. Sequencing and details will be refined as we
build, but the decisions recorded in Section 3 are settled.

---

## 1. Where we are today

The repository is currently a single-tenant **batch pipeline**, not a web
application:

- A Python 3.10+ command-line pipeline (only runtime dependency: `requests`;
  persistence via the standard-library `sqlite3`).
- It pulls real CVE and CISA KEV data from the public NVD 2.0 API, scores **12
  hardcoded vendors** on a threat x exposure matrix, and renders a **single
  self-contained `dashboard.html`** plus a `watchlist.csv`.
- There is no authentication, no server, no database-backed UI, and no
  interactivity. The published "live demo" is a pre-rendered HTML snapshot served
  by GitHub Pages.

What matters for this plan: **the domain core is already clean, pure, and
well-tested** (38 passing tests) and carries forward almost unchanged. The work
ahead is building the web-application layer on top of it.

Reusable assets:

- **Risk model** (`src/scoring.py`) — pure functions over an editable lookup
  matrix. Ports verbatim.
- **NVD client** (`src/nvd_client.py`) — pagination, backoff, and rate-limit
  pacing already handled.
- **CVE parser** (`src/parser.py`) — normalization, including the rule that a
  missing CVSS score is `NULL`, never `0.0`.
- **Persistence semantics** (`src/db.py`) — idempotent upserts and an
  append-only audit log.

---

## 2. Vision and goals

**Vision.** A vendor-risk monitoring product a team can actually run: add the
vendors you depend on, and the system continuously measures their published-
vulnerability exposure, tells you when something changes, and gives you
audit-ready reporting — without the noise and false comfort most tools produce.

**Target users.** Security, IT, and procurement teams who need a defensible,
low-noise view of third-party software risk.

**Guiding principles.**

1. **Honest data over reassuring data.** Never turn missing data into a
   reassuring number. "Unscored" is never `0.0`; "Not Assessed" is never "Low".
   Keep the scope disclaimer that separates *published vulnerabilities* from
   *confirmed compromise*.
2. **Reuse the proven core.** The scoring engine and NVD integration are assets;
   build around them rather than rewriting them.
3. **Corporate-minimalist design.** A restrained, professional interface (see
   Section 9). Clarity over decoration.
4. **Multi-tenant from day one.** Retrofitting tenancy later is painful; the data
   model is org-scoped from the start.

---

## 3. Product decisions (locked)

| Area | Decision |
|------|----------|
| **Backend stack** | FastAPI (Python), reusing the existing domain core as a library |
| **Frontend stack** | React single-page app (TypeScript) |
| **Database** | PostgreSQL in production (SQLite semantics carried over) |
| **Tenancy** | Organization / team workspaces; users belong to an org (an org can have a single user) |
| **Priority features** | Alerts & notifications; scheduled auto-sync + risk trends; reporting & export; smart vendor onboarding (CPE + SBOM) |
| **Design language** | Corporate minimalism — solid, professional palette only (no vibrant, pastel, or muted colors), no emojis |
| **Theming** | First-class light and dark mode |
| **Home dashboard** | Per-user customizable board of chart/graph widgets: add up to 5, reduce to none, each widget fluidly expands and minimizes |

---

## 4. Target architecture

A FastAPI API and a Celery worker both import a shared `core/` package. Postgres
is the system of record; Redis is the broker and rate-limit store; a React SPA is
the client.

```
                 +---------------------------+
                 |   React SPA (Vite + TS)   |
                 |  TanStack Query, Recharts |
                 +-------------+-------------+
                               | HTTPS (JWT in httpOnly cookie)
                               v
      import  +-------------------------------+  import
 +-----------> |         FastAPI  API          | <-----------+
 |            |  auth, RBAC, org-scoping      |             |
 |            |  serves JSON, enqueues jobs   |             |
 |            +---+-----------+----------+----+             |
 |    SQLAlchemy  |          | enqueue  | read/write        |
 |                v          v (Redis)                       |
+--+---------+ +----------+ +---------------+        +-------+---------+
|  core/     | | Postgres | |     Redis     |  jobs  |  Celery Worker  |
|  scoring   | | tenants  | | broker, cache | <----> |  sync, snapshot |
|  parser    | | vulns    | | rate-limit    |        |  alerts, notify |
|  nvd_client| | snapshots| +-------+-------+        |  export         |
|  sync      | +----+-----+         | schedule       +---+--------+----+
+------------+      |         +------+------+            |        | external
                    +---------+ Celery Beat |            |        v
                      read    | (dispatcher)|            |  +--------------------+
                              +-------------+            +->| NVD 2.0, SMTP,     |
                                                            | Slack              |
                                                            +--------------------+
```

**How components interact.** The SPA calls the JSON API over HTTPS, carrying a
JWT in an httpOnly cookie. The API owns all synchronous Postgres reads and writes
and enqueues background jobs onto Redis. The worker consumes jobs, calls the
`core/` package (which reaches NVD, SMTP, and Slack), and writes results back to
Postgres. Celery Beat is a thin scheduler: on a cron it enqueues a single
dispatcher job and holds no per-tenant state.

**Why this shape.** The existing `nvd_client` is synchronous and already
dependency-injected, so a synchronous Celery worker runs it unchanged. Keeping the
same `core/` package on both sides means business logic has exactly one home.

---

## 5. Backend: reuse the core, add a web layer

Split the codebase into a dependency-light `core/` domain library and an `app/`
web layer. ORM: **SQLAlchemy 2.0 (sync) + psycopg3**. Migrations: **Alembic**.

```
core/            scoring.py      # keep verbatim
                 parser.py       # keep verbatim
                 nvd_client.py   # add api_key; demo caps become arguments
                 sync.py         # extracted from pipeline.ingest (engine-agnostic)
                 constants.py    # SCOPE_DISCLAIMER, severity tokens, watchlist rule, bands
app/
  main.py        # FastAPI app factory, routing, middleware, CORS
  config.py      # pydantic-settings: DB, Redis, JWT, encryption key, SMTP, ...
  db.py          # SQLAlchemy engine/session, Base
  deps.py        # get_db, get_current_user, get_current_org, require_role
  security.py    # Argon2 hashing, JWT, secret encryption
  models/        # org, user, membership, invitation, user_preferences, vendor,
                 # vulnerability, cpe_sync_state, risk_snapshot, alert_rule,
                 # notification, sync_run, audit_log
  schemas/       # Pydantic request/response DTOs
  api/           # auth, orgs, members, me, vendors, vulns, dashboard,
                 # snapshots, alerts, exports, sync
  services/      # scoring_service, sync_service, onboarding, alerts_service,
                 # notify, export
  workers/       # celery_app, tasks, beat
migrations/      # Alembic env + versions
frontend/        # React + Vite + TS (Section 9)
pyproject.toml   # replaces requirements.txt; ruff / mypy / pytest config
docker-compose.yml
.env.example
```

**Keep, adapt, replace.**

- **Keep verbatim** — `scoring.py`, `parser.py`.
- **Adapt** — `nvd_client.py` gains an `api_key` parameter and turns its demo caps
  (119-day window, 3-page limit, keyless pacing) into arguments;
  `pipeline.ingest()` becomes `core/sync.py` plus `services/sync_service.py`; the
  `pipeline.run()` CLI survives for offline development and seeding.
- **Replace** — `report.py` (superseded by the React UI and the PDF export) and
  the raw-SQL `db.py` (superseded by SQLAlchemy models). Their **semantics are
  preserved**: `INSERT ... ON CONFLICT DO UPDATE` upserts, the "never overwrite
  good data with an empty result" rule, the scope disclaimer, and the watchlist
  selection rule.

---

## 6. Data model (SQLite to Postgres)

Core insight: **CVE data is public and identical for every tenant, but exposure
(business context) is per-tenant.** So the vulnerability cache is shared/global
and everything derived from business context is per-org.

**Global**

- `organizations` — id, name, slug, plan, created_at.
- `users` — id, email (unique), password_hash (nullable, for future OAuth), name,
  is_active, last_login_at.
- `vulnerabilities` — one row per CVE (no `org_id`; deduplicated across tenants):
  cvss_score (nullable, never `0.0`), cvss_version, cvss_severity, is_kev, KEV
  dates, published/last-modified dates, status, description.
- `cpe_sync_state` — per CPE prefix: last-modified watermark, last full backfill,
  subscriber count. Drives incremental sync.

**Per-organization**

- `memberships` — user <-> org with role (owner / admin / member / viewer).
- `invitations` — tokenized email invites with expiry.
- `org_integrations` — encrypted secrets (NVD API key, Slack webhook, SMTP);
  write-only over the API.
- `vendors` — now FK to org: name, `cpe_prefix`, `match_method`, business context
  (annual contract value, data sensitivity, business criticality, renewal date),
  `last_synced_at`, `next_sync_at`.
- `vendor_vulnerabilities` — junction (per-org via the org-scoped vendor).
- `risk_snapshots` — append-only time series (tier, bands, max CVSS, CVE/KEV
  counts, captured_at) powering trends and audit history.
- `alert_rules`, `notifications` (with a unique `dedup_key`), `sync_runs`
  (evolves `ingest_runs`), `audit_log`.

**Per-user**

- `user_preferences` — the user's `theme` (light / dark / system) and their home
  dashboard layout: an ordered list of at most 5 widgets, each with a type,
  config, and size/expanded state (a `jsonb` layout column or a small
  `dashboard_widgets` child table). The **5-widget limit is enforced in the
  service layer**, not only the UI.

Upserts keep current behavior via `insert(...).on_conflict_do_update(...)`; the
"keep prior good rows on a partial sync" rule moves into `sync_service`.

---

## 7. Authentication and multi-tenancy

- **Sessions.** JWT delivered in httpOnly, Secure, SameSite cookies: a
  short-lived access token plus a longer refresh token. A Redis revocation set can
  be added when "log out everywhere" is needed.
- **Passwords.** Argon2 hashing. `users.password_hash` is nullable so Google
  OAuth (later) links to the same user row.
- **Org scoping.** Routes are `/api/v1/orgs/{org_id}/...`. A single dependency
  verifies the caller has a membership for that org, loads the role, and returns
  an org context. Every org-scoped query filters by `org_id`, and services take
  `org_id` as a required argument, so a stray query cannot leak across tenants.
- **Roles (RBAC).** `owner > admin > member > viewer`, enforced by a
  `require_role` dependency. Viewer reads and exports; member manages vendors and
  runs syncs; admin manages members, integrations, and alert rules; owner handles
  billing and org deletion.
- **Invites.** Admin creates an invitation; the invitee follows a tokenized link,
  registers or signs in, and accepts, which creates the membership.

---

## 8. API surface (`/api/v1`)

```
Auth            POST /auth/register, /auth/login, /auth/refresh, /auth/logout; GET /auth/me
Orgs & members  POST/GET /orgs; GET|PATCH|DELETE /orgs/{id}; members, invitations, integrations
Me & prefs      GET|PUT /me/preferences                 # theme
                GET|PUT /orgs/{id}/me/dashboard         # personal home board: widgets (max 5)
Vendors         GET/POST /orgs/{id}/vendors (q, tier, sort, renewal_before, page)
                GET|PATCH|DELETE /orgs/{id}/vendors/{vid}
                POST /orgs/{id}/vendors/{vid}/sync; :onboard (name->CPE); :import-sbom
Vulnerabilities GET /orgs/{id}/vendors/{vid}/vulnerabilities; GET /vulnerabilities/{cve}
Dashboard       GET /orgs/{id}/dashboard/summary, /heatmap, /watchlist  (widget data)
Trends          GET /orgs/{id}/snapshots; /orgs/{id}/vendors/{vid}/trend
Alerts          GET/POST /orgs/{id}/alert-rules; GET /orgs/{id}/notifications
Exports & audit POST /orgs/{id}/exports (csv|pdf) -> job; GET /exports/{id}; /sync-runs; /audit-log
Ops             GET /healthz, /readyz
```

---

## 9. Frontend, design system, and the customizable dashboard

**Stack.** React + TypeScript + Vite, React Router, TanStack Query for server
state, React Hook Form + Zod for forms. Charts: Recharts for time series and
distributions; a CSS-grid heatmap for the 4x4 risk matrix. Icons: a professional
line-icon set (for example, lucide-react) — never emojis.

### Design language: corporate minimalism

- A solid, professional palette only: a neutral base (white / graphite / slate
  scale) with a single restrained accent. **No vibrant colors, no pastels, no
  muted or washed-out colors, no decorative gradients, no emojis.**
- Generous whitespace, a strong type hierarchy, thin dividers, and tabular
  numerals for all figures.
- All color is defined as **design tokens** so themes swap cleanly.
- The risk-tier / severity scale is redrawn from the demo's pastel tints into a
  restrained, high-contrast professional scale that stays legible and WCAG-AA in
  both themes and **never relies on hue alone** — severity always carries a text
  label or badge. Exact tokens are finalized during implementation using the
  project's data-visualization palette methodology.

### Light and dark mode

System-aware by default with an explicit user toggle (light / dark / system).
Implemented via CSS custom properties and a `data-theme` attribute; both themes
are first-class, not a bolt-on. The preference persists per user on the server
(`user_preferences`) and in `localStorage` for an instant, flash-free load.

### Customizable home dashboard (0 to 5 widgets)

The home page is a personal, per-user board of chart/graph widgets:

- The user **adds up to 5 widgets and can remove down to none.**
- Each widget **fluidly expands and minimizes** — smooth size and height
  transitions between a compact header state and a detailed view — and can be
  reordered and resized.
- **Widget catalog:** tier distribution, risk heatmap, KEV exposure, CVE trend
  over time, upcoming renewals / watchlist, top-risk vendors, and data-health /
  last-sync.
- **Implementation:** a resizable, draggable grid (react-grid-layout or dnd-kit)
  with fluid motion (Framer Motion or CSS transitions). The 5-widget limit is
  enforced in both the UI and the API. Layout and per-widget state are saved per
  user (Sections 6 and 8), so a board restores across sessions and devices. A
  clean empty state (0 widgets) offers an "add a widget" prompt.

### Pages

Login / register / accept-invite; **home dashboard** (the widget board above);
vendor list (filter, search, sort, paginate; add / onboard / SBOM import); vendor
detail (bands, CVE list, trend chart, sync-now); alerts configuration and
notification feed; reports / export center; org settings (members, roles, invites,
integrations, sync schedule) and personal settings (theme).

The honesty helpers carry into the UI: "Unscored" (never `0.0`), "Not Assessed"
(never "Low"), and the scope disclaimer in the footer and every export.

---

## 10. Feature designs

**Alerts and notifications.** Typed `alert_rules`: `new_kev`, `tier_change`,
`renewal_due`. KEV and tier rules are evaluated when a sync produces a new
snapshot, by diffing against the prior snapshot and scanning the sync delta;
renewal rules run on a daily scan of High/Critical vendors within N days.
Matches write `notifications` with a unique `dedup_key`
(`org:vendor:type:cve:date`), so a re-sync never produces duplicate alerts, and
dispatch email (SMTP) or a per-org Slack webhook with retries.

**Scheduled auto-sync and trends.** A per-org cadence sets each vendor's
`next_sync_at`. Beat's dispatcher enqueues due CPE prefixes, deduplicated so a
prefix shared by many orgs is fetched once. Incremental sync uses NVD's
`lastModStartDate` watermark (catching both new CVEs and CVSS/KEV changes on
existing ones). Every sync appends `risk_snapshots`; trend endpoints downsample by
interval; the SPA renders tier, max-CVSS, and CVE/KEV lines over time and feeds
the trend widgets on the home board.

**Reporting and export.** Server-side CSV (reusing the existing watchlist columns)
and PDF via WeasyPrint (reusing the report structure, severity tokens, and scope
disclaimer). Exports run as background jobs, are stored to object storage, and are
returned as signed download URLs. `audit_log` and `risk_snapshots` back an
audit-ready history. Vendor and CVE lists support filter, search, and sort.

**Smart vendor onboarding (CPE and SBOM).** Name-to-CPE onboarding probes NVD with
`virtualMatchString=cpe:2.3:a:<slug>`, returns candidate prefixes ranked by
`totalResults` for the user to confirm (recording `match_method = virtual_match`,
falling back to `keyword`). SBOM import accepts CycloneDX/SPDX JSON, extracts
components, maps embedded CPEs/PURLs to prefixes, and bulk-creates vendors with
suggested mappings for review, then triggers a one-time backfill.

---

## 11. Deployment, infrastructure, and CI

**Containers (Docker Compose).** `api` (gunicorn + uvicorn workers), `worker`
(Celery), `beat` (Celery Beat), `postgres`, `redis`, `frontend` (nginx serving the
built SPA), and an optional `flower` for queue observability.

**Secrets and configuration.** Provided via environment, never committed:
`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `APP_ENCRYPTION_KEY` (for org secrets),
`NVD_API_KEY` (system fallback), `SMTP_*`, Slack defaults, and OAuth credentials
(later). Per-org secrets are envelope-encrypted at rest and are write-only over
the API.

**Hosting.** For a small team, Render maps cleanly onto this shape: managed
Postgres and Redis, a Background Worker each for the worker and Beat, and a Static
Site for the SPA. Fly.io and Railway are viable alternatives.

**CI (GitHub Actions).** Backend: ruff + mypy + pytest against a Postgres service
container (the fast offline fixture tests stay). Frontend: eslint + `tsc
--noEmit` + vitest + build. Build Docker images, and trigger the deploy hook on
`main`.

---

## 12. Phased roadmap

**Phase 0 — Harden and refactor (no user-facing change).**
Add `pyproject.toml`; move `src/` to `core/`; extract `core/sync.py`; add API-key
support and configurable caps to `nvd_client`; lift the report constants into
`core/constants.py`; author SQLAlchemy models and the first Alembic migration
(porting the upsert and integrity semantics); Dockerize. Keep all 38 tests green
and add Postgres integration tests. Also fix the dangling `DEMO_BUILD_SPEC.md`
reference in `src/__init__.py`.

**Phase 1 — MVP SaaS.**
Auth (JWT cookies), orgs, memberships, and RBAC; org-scoped vendor CRUD;
on-demand sync (system key); the design system and light/dark theming; the
customizable home dashboard (add/remove up to 5 widgets, fluid expand/minimize,
layout saved per user) with the initial widget set (tier distribution, heatmap,
watchlist, KEV exposure, top-risk vendors); the vendor list; and vendor detail.
*Ships: a real, themeable product with a personal dashboard, that you add vendors
to and sync by hand.*

**Phase 2 — Automation.**
The Beat dispatcher, per-org schedule, incremental sync, and stored per-org NVD
key; `risk_snapshots` and trend charts (including trend widgets on the home
board); alert rules with email and Slack delivery. *Ships: the product runs itself
and tells you when something changes.*

**Phase 3 — Reporting and onboarding.**
CSV and PDF export, an export center, and a surfaced audit log; advanced filter,
search, and sort; name-to-CPE onboarding and SBOM import. *Ships: fast, accurate
vendor addition and audit-ready reporting.*

**Phase 4 — Scale and polish.**
Google OAuth / SSO, Stripe billing, rate-limit hardening (per-key token buckets,
backfill queue tuning), object storage for exports, and observability (Flower,
Sentry, structured logs). *Ships: production-grade multi-tenant SaaS.*

---

## 13. What we preserve vs. remove

**Preserve (these are differentiators).**

- The risk model, including the deliberate rule that a KEV floors a vendor at High
  rather than forcing Critical (which would collapse the exposure axis).
- "Unscored" is never `0.0`; "Not Assessed" is never "Low".
- A partial sync keeps prior good rows instead of overwriting them with empty
  results.
- The scope disclaimer, verbatim, in the app footer and every export.

**Remove (demo scaffolding).**

- The synthetic business-data generator from the product path (kept only as a
  development seed; the saved NVD fixtures remain as the test corpus).
- "Demo Edition", the portfolio ribbon, the synthetic-data banner, and the
  fixed-12-vendor framing.
- The 119-day / 3-page / keyless caps (replaced by incremental sync with a stored
  API key).
- All emojis (for example, the warning glyph in the synthetic-data notice),
  replaced by professional line icons.
- The pastel tier tints, redrawn into the corporate-minimalist severity scale for
  both themes.

---

## 14. Key risks and decisions

- **NVD rate limits and data volume.** The keyless limit is too slow past a
  handful of vendors, so scheduled sync requires a stored API key. A shared cache
  plus incremental (`lastMod`) sync keeps steady state cheap; the one-time
  per-prefix backfill is the expensive path and is queued and paced. A Redis token
  bucket keyed by API key enforces the limit across all workers.
- **Shared vs. per-org cache (decided).** `vulnerabilities` and `cpe_sync_state`
  are global (public data, deduplicated); scoring, snapshots, and alerts are
  per-org (exposure differs). The shared cache is maintained with a system key; a
  stored per-org key gives that org its own throughput for on-demand syncs.
- **Secret handling.** Org secrets are envelope-encrypted at rest, write-only over
  the API, and never logged. `JWT_SECRET` and the encryption key come from the
  platform secret store.
- **Security and privacy.** Minimal PII (email, name), Argon2 hashing, httpOnly
  cookies, HTTPS only, and per-tenant authorization on every query.
- **Design tension.** A professional palette with no vibrant, pastel, or muted
  colors must still encode severity clearly. Resolved by a restrained,
  high-contrast scale plus always-present text labels, so meaning never depends on
  hue alone.

---

## 15. Reuse map — existing code

| Existing file | Role in the new system |
|---------------|------------------------|
| `src/scoring.py` | Pure risk model (`threat_band`, `exposure_band`, `MATRIX`, `final_tier`, `assess`). Ports verbatim into `core/`. |
| `src/db.py` | Table shapes, `INSERT ... ON CONFLICT DO UPDATE` upserts, and the "no bulk-DELETE / keep prior good rows" rule. Blueprint for the SQLAlchemy models and first migration. |
| `src/nvd_client.py` | Synchronous NVD client (pagination, backoff, pacing). Gains an `api_key` parameter and caps-as-arguments. |
| `src/pipeline.py` | The `run()` / `ingest()` dependency-injected shape becomes `core/sync.py`, `services/sync_service.py`, and the Celery tasks. The synthetic generator becomes a development seed only. |
| `src/report.py` | Replaced by the React UI and PDF export, but `SCOPE_DISCLAIMER`, the watchlist rule and columns, and the "Unscored / Not Assessed" display logic move into `core/constants.py`, the frontend theme, and the export template. `TIER_STYLE` is the reference point that gets redrawn into professional light/dark severity tokens. |
| `README.md` | The "What the full version adds" section (Docker, PostgreSQL, incremental sync with a stored key, SBOM-driven CPE mapping) is the seed this plan expands. |

---

## Appendix: the risk model (for reference)

**Threat band** (from a vendor's CVEs): `T4` any KEV; `T3` max CVSS >= 9.0 or at
least three CVEs >= 7.0; `T2` max CVSS >= 7.0; `T1` otherwise. Unscored (NULL)
CVSS values never count toward these thresholds.

**Exposure band** (from business context, highest wins): `E4` regulated or ACV >=
500k; `E3` confidential or ACV >= 100k or criticality high; `E2` ACV >= 25k; `E1`
otherwise.

**Final tier** is a fixed lookup, not arithmetic:

|        | E1 | E2 | E3 | E4 |
|--------|----|----|----|----|
| **T4** | High | High | Critical | Critical |
| **T3** | Medium | High | High | Critical |
| **T2** | Low | Medium | Medium | High |
| **T1** | Low | Low | Low | Medium |

Unmapped or failed vendors are "Not Assessed" and never enter the matrix.
