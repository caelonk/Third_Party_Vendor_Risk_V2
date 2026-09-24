# Vendor Risk Platform

Multi-tenant SaaS for continuous **third-party vendor vulnerability risk**
scoring. Teams sign in, add the vendors they depend on, and get continuous
published-vulnerability risk scoring from real NVD / CISA KEV data, with
automated monitoring, alerting, reporting, and a customizable dashboard.

Built on the proven, pure risk model from the original demo
([`caelonk/vendor-risk-dashboard`](https://github.com/caelonk/vendor-risk-dashboard)),
now wrapped in a real web application.

> **Scope.** This tool measures *published vulnerabilities in vendor products*.
> It does not measure whether a vendor has been breached, the vendor's internal
> security posture, or whether this organization is actually exposed. A high
> score means "investigate," not "compromised."

## Honest-data guarantees

These are non-negotiable and carry from the demo into every layer:

- **"Unscored" is never `0.0`.** A missing CVSS score stays `NULL`; it never
  counts toward thresholds and never renders as a zero.
- **"Not Assessed" is never "Low".** An unmapped or failed-fetch vendor is a
  distinct state — absence of data is not evidence of low risk.
- **A partial sync keeps prior good rows.** A vendor whose fetch fails is never
  downgraded or wiped; its last good data stands.
- **KEV floors a vendor at High, not Critical** — deliberately, so the exposure
  axis is not collapsed. The final tier is a fixed lookup matrix, not arithmetic.

## Architecture

```
React SPA ──HTTPS(JWT cookie)──▶ FastAPI API ──▶ PostgreSQL (system of record)
    │                                │      └──▶ Redis (broker + rate-limit)
    │ signed download link           ▼ enqueue
    └──────────▶ Object storage ◀── Celery worker ──▶ NVD 2.0 / SMTP / Slack
                 (S3 / MinIO)       Celery Beat (cron dispatcher)
```

CVE data is public and identical for every tenant, so the `vulnerabilities`
cache is **global** (deduplicated by CVE); everything derived from business
context is **per-org**. The API and the worker both import the same dependency-
light `core/` package, so business logic has exactly one home.

| Layer | Stack |
|-------|-------|
| Backend | FastAPI, SQLAlchemy 2.0 (sync) + psycopg3, Alembic |
| Domain core | `core/` — scoring, parser, NVD client, sync (only `requests`) |
| Background | Celery + Redis + Celery Beat |
| Auth | JWT (httpOnly cookies), Argon2id, RBAC (owner/admin/member/viewer) |
| Database | PostgreSQL |
| Object storage | Any S3-compatible store (MinIO locally) — export files |
| Frontend | React + TypeScript + Vite *(Phase 1)* |

## Repository layout

```
core/          Pure domain library (scoring, parser, nvd_client, sync, constants)
app/           FastAPI web layer (models, config, db, security, deps, api, workers)
seed/          Dev-only offline pipeline (SQLite + static HTML snapshot)
migrations/    Alembic (env + versions)
tests/         Pytest suite + saved NVD fixture corpus
config/        vendors.yml (CPE prefix map)
```

## Quickstart (Docker)

```bash
cp .env.example .env          # then edit secrets (see below)
docker compose up --build
```

Open **<http://localhost:8080>** — nginx serves the built SPA and proxies `/api`
on the same origin (so the httpOnly auth cookies just work). The stack:

| Service    | Role |
|------------|------|
| `migrate`  | One-shot `alembic upgrade head`; everything else waits for it to succeed. |
| `api`      | FastAPI under gunicorn + uvicorn workers (also on `127.0.0.1:8000` for the Vite dev server; `/healthz`, `/readyz`, `/api/docs`). |
| `worker`, `beat` | Celery worker (incremental syncs) and the scheduled-sync dispatcher (same image). |
| `worker-backfill` | A product's first, expensive NVD pull, on its own queue — so a big import never delays routine syncs. |
| `frontend` | nginx: SPA, `/api` proxy, security headers + CSP, long-cached hashed assets. |
| `minio`    | S3-compatible storage for exports (<http://localhost:9001> console). A local stand-in: MinIO no longer publishes images, so the last community release is pinned. |
| `flower`   | Optional queue dashboard: `FLOWER_BASIC_AUTH=user:pass docker compose --profile ops up -d flower` → <http://localhost:5555>. |

Every NVD call (worker syncs, the Sync button, CPE search) draws from one Redis
token bucket per API key, so NVD's rate limit holds across all processes;
backfills must leave a 30% cushion (`NVD_BACKFILL_RESERVE_FRACTION`).

**Exports** (CSV data, PDF report) are background jobs: the API queues one, a
worker renders it into the bucket, and the SPA polls and then follows
`/exports/{id}/download`, which checks membership and redirects to a signed URL
valid for 5 minutes. Files are deleted after 7 days by a Beat task, which also
fails jobs a dead worker left behind. Point `S3_*` at AWS S3, R2, or any
S3-compatible store in production; `EXPORT_STORAGE=local` (plus
`EXPORT_RUN_INLINE=true` without Redis) covers development outside Docker.

All published ports bind to `127.0.0.1`. Logs are JSON (one object per line);
every response carries an `X-Request-ID` that also appears on the matching nginx
and API log lines. Set `SENTRY_DSN` to enable error reporting.

**Generate the required secrets** before first run:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # APP_ENCRYPTION_KEY
```

## Local development

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                 # full suite (offline, SQLite)
ruff check .           # lint
mypy core app          # type-check

# Offline dev seed: replay the saved NVD fixtures into a local SQLite snapshot.
python -m seed.pipeline --offline
```

## Testing

The suite is **offline and deterministic** — it replays a saved NVD fixture
corpus, so there is no network dependency. Model and app-layer tests run against
in-memory SQLite; the Alembic migration is verified against PostgreSQL in CI.

## Roadmap status

- **Phase 0 — Harden & refactor (done):** repo skeleton, ported `core/`,
  SQLAlchemy models + first migration, app shell, Docker/CI. No user-facing change.
- **Phase 1 — MVP SaaS:** auth/orgs/RBAC, vendor CRUD, on-demand sync, design
  system + light/dark, customizable dashboard, vendor list/detail.
- **Phase 2 — Automation:** scheduled incremental sync, risk trends, alerts.
- **Phase 3 — Reporting & onboarding:** CSV/PDF export, CPE + SBOM onboarding.
- **Phase 4 — Scale & polish:** OAuth/SSO, billing, observability.

See [`PLAN.md`](PLAN.md) and [`HANDOFF.md`](HANDOFF.md) for the full plan.
