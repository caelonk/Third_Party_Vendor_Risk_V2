"""Portfolio reporting: CSV data export and a formatted PDF report.

Every export carries the scope disclaimer verbatim (a locked integrity rule), and
honest-data rules hold on the way out: an unscored vendor exports a blank Max
CVSS (never 0.0) and keeps its "Not Assessed" tier (never "Low").

WeasyPrint (HTML->PDF) needs GTK/Pango system libraries that exist in the Docker
image but not on a bare dev box or CI, so it is imported lazily inside
:func:`portfolio_pdf` only; the CSV and the HTML body are pure and portable.

Exports run as background jobs (:func:`create_job` -> worker :func:`run_job`):
the rendered file goes to object storage, and a download is a short-lived signed
URL issued per request (:func:`signed_download_url`). :func:`purge` deletes files
past retention and fails jobs a dead worker left behind.
"""
from __future__ import annotations

import csv
import html
import io
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Select, func, select, update
from sqlalchemy.orm import Session

from core.constants import SCOPE_DISCLAIMER

from ..config import get_settings
from ..models import ExportFormat, ExportJob, ExportStatus, Organization, User
from . import scoring_service, vendor_service
from .exceptions import ConflictError, GoneError, NotFoundError, TooManyRequestsError
from .object_storage import ObjectStorage

log = logging.getLogger(__name__)

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
    vendors = vendor_service.list_vendors(db, org_id)
    assessed = scoring_service.assess_vendors(db, vendors)  # one batched CVE query
    for v in vendors:
        a = assessed[v.id]
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


# --------------------------------------------------------------------------- #
# Background export jobs                                                       #
# --------------------------------------------------------------------------- #
CONTENT_TYPES = {
    ExportFormat.csv: "text/csv; charset=utf-8",
    ExportFormat.pdf: "application/pdf",
}
_ACTIVE = (ExportStatus.queued, ExportStatus.running)

# User-facing failure text (stored on the job). Details go to the logs only.
PDF_UNAVAILABLE = "PDF rendering is not available on this server."
RENDER_FAILED = "The export could not be generated. Try again in a moment."
DISPATCH_FAILED = "Background processing is unavailable right now. Try again shortly."
TIMED_OUT = "The export did not finish in time. Try again."


@dataclass
class ExportJobView:
    id: int
    format: ExportFormat
    status: ExportStatus
    filename: str | None
    size_bytes: int | None
    error: str | None
    requested_by: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    # SQLite (tests) hands datetimes back naive; every stored time is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _is_past_retention(job: ExportJob, now: datetime) -> bool:
    return job.expires_at is not None and _aware(job.expires_at) <= now


def create_job(db: Session, org_id: int, user_id: int | None, fmt: ExportFormat) -> ExportJob:
    """Queue an export. A soft per-org cap stops one tenant flooding the workers."""
    active = db.scalar(
        select(func.count())
        .select_from(ExportJob)
        .where(ExportJob.org_id == org_id, ExportJob.status.in_(_ACTIVE))
    )
    if (active or 0) >= get_settings().export_max_active_per_org:
        raise TooManyRequestsError(
            "Several exports are already being prepared. Wait for them to finish, then try again."
        )
    job = ExportJob(
        org_id=org_id, requested_by_user_id=user_id, format=fmt, status=ExportStatus.queued
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def mark_failed(db: Session, job_id: int, message: str) -> None:
    db.execute(
        update(ExportJob)
        .where(ExportJob.id == job_id, ExportJob.status.in_(_ACTIVE))
        .values(status=ExportStatus.failed, error=message, completed_at=_now())
        .execution_options(synchronize_session=False)
    )
    db.commit()


def render(db: Session, org: Organization, fmt: ExportFormat) -> bytes:
    if fmt is ExportFormat.csv:
        return portfolio_csv(db, org.id, org).encode("utf-8")
    return portfolio_pdf(db, org.id, org)


def run_job(
    db: Session, job_id: int, storage: ObjectStorage, *, now: datetime | None = None
) -> ExportJob | None:
    """Render one export and store it. Safe to deliver twice.

    The queued -> running transition is a conditional UPDATE, so exactly one
    delivery claims the job (tasks are acks_late, so redelivery happens). A job
    that isn't queued any more is returned untouched.
    """
    started = now or _now()
    claimed = cast(
        CursorResult,
        db.execute(
            update(ExportJob)
            .where(ExportJob.id == job_id, ExportJob.status == ExportStatus.queued)
            .values(status=ExportStatus.running, started_at=started)
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    db.commit()
    job = db.get(ExportJob, job_id)
    if job is None or claimed != 1:
        return job

    org = db.get(Organization, job.org_id)
    assert org is not None  # FK + cascade: a job never outlives its org
    content_type = CONTENT_TYPES[job.format]
    name = filename(org, job.format.value)
    # A random path segment: keys are never guessable, even though every
    # download is signed anyway.
    key = f"exports/{org.id}/{secrets.token_hex(16)}/{name}"
    try:
        data = render(db, org, job.format)
        storage.put(key, data, content_type=content_type)
    except Exception as exc:
        db.rollback()
        if job.format is ExportFormat.pdf and isinstance(exc, ImportError | OSError):
            # WeasyPrint or its GTK/Pango libraries are missing on this host.
            log.warning("export %d: PDF rendering unavailable: %s", job_id, exc)
            message = PDF_UNAVAILABLE
        else:
            log.exception("export %d failed", job_id, extra={"export_job_id": job_id})
            message = RENDER_FAILED
        mark_failed(db, job_id, message)
        db.refresh(job)
        return job

    finished = now or _now()
    job.status = ExportStatus.succeeded
    job.filename = name
    job.content_type = content_type
    job.object_key = key
    job.size_bytes = len(data)
    job.completed_at = finished
    job.expires_at = finished + timedelta(hours=get_settings().export_retention_hours)
    db.commit()
    log.info(
        "export %d stored (%s, %d bytes)", job_id, job.format.value, len(data),
        extra={"export_job_id": job_id, "bytes": len(data)},
    )
    return job


def _view(job: ExportJob, email: str | None, name: str | None, now: datetime) -> ExportJobView:
    status = job.status
    # Past retention but not purged yet: report it as expired, never as ready.
    if status is ExportStatus.succeeded and _is_past_retention(job, now):
        status = ExportStatus.expired
    return ExportJobView(
        id=job.id,
        format=job.format,
        status=status,
        filename=job.filename,
        size_bytes=job.size_bytes,
        error=job.error,
        requested_by=name or email,
        created_at=job.created_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
    )


def _job_query(org_id: int) -> Select[Any]:
    return (
        select(ExportJob, User.email, User.name)
        .outerjoin(User, User.id == ExportJob.requested_by_user_id)
        .where(ExportJob.org_id == org_id)
        # Jobs change under this session (a worker, or the inline runner, writes
        # through its own): always read the row, never a cached identity.
        .execution_options(populate_existing=True)
    )


def list_jobs(db: Session, org_id: int, *, limit: int = 20) -> list[ExportJobView]:
    now = _now()
    rows = db.execute(
        _job_query(org_id).order_by(ExportJob.created_at.desc(), ExportJob.id.desc()).limit(limit)
    ).all()
    return [_view(job, email, name, now) for job, email, name in rows]


def get_job(db: Session, org_id: int, job_id: int) -> ExportJobView:
    row = db.execute(_job_query(org_id).where(ExportJob.id == job_id)).first()
    if row is None:  # includes another org's job: never disclose it exists
        raise NotFoundError("Export not found")
    job, email, name = row
    return _view(job, email, name, _now())


def signed_download_url(
    db: Session, org_id: int, job_id: int, storage: ObjectStorage
) -> str:
    """A fresh, short-lived link to the stored file (checked per request)."""
    job = db.scalar(
        select(ExportJob).where(ExportJob.id == job_id, ExportJob.org_id == org_id)
    )
    if job is None:
        raise NotFoundError("Export not found")
    if job.status is ExportStatus.expired or (
        job.status is ExportStatus.succeeded and _is_past_retention(job, _now())
    ):
        raise GoneError("This export has expired. Generate a new one.")
    if job.status is ExportStatus.failed:
        raise ConflictError("This export failed. Generate a new one.")
    if job.status is not ExportStatus.succeeded or not job.object_key:
        raise ConflictError("This export is still being prepared.")
    return storage.signed_url(
        job.object_key,
        filename=job.filename or f"export.{job.format.value}",
        content_type=job.content_type or CONTENT_TYPES[job.format],
        expires_in=get_settings().export_url_ttl_seconds,
    )


def purge(db: Session, storage: ObjectStorage, *, now: datetime | None = None) -> dict[str, int]:
    """Delete stored files past retention; fail jobs stuck by a dead worker.

    A file whose delete fails stays ``succeeded`` (downloads are already refused
    past ``expires_at``) and is retried on the next run.
    """
    now = now or _now()
    settings = get_settings()

    expired = 0
    for job in db.scalars(
        select(ExportJob).where(
            ExportJob.status == ExportStatus.succeeded, ExportJob.expires_at <= now
        )
    ).all():
        try:
            if job.object_key:
                storage.delete(job.object_key)
        except Exception:  # noqa: BLE001 — retried next run
            log.warning("export %d: could not delete %s; will retry", job.id, job.object_key)
            continue
        job.status = ExportStatus.expired
        job.object_key = None
        expired += 1

    cutoff = now - timedelta(minutes=settings.export_stale_after_minutes)
    timed_out = cast(
        CursorResult,
        db.execute(
            update(ExportJob)
            .where(ExportJob.status.in_(_ACTIVE), ExportJob.created_at < cutoff)
            .values(status=ExportStatus.failed, error=TIMED_OUT, completed_at=now)
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    db.commit()
    if expired or timed_out:
        log.info("export purge: %d expired, %d timed out", expired, timed_out)
    return {"expired": expired, "timed_out": timed_out}
