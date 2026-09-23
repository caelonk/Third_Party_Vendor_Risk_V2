"""On-demand vendor sync: fetch CVEs, upsert the shared cache, snapshot risk.

Reuses ``core.sync.ingest`` (the same orchestration the dev seed uses) with the
SQLAlchemy store. The NVD ``fetch`` port is injected so the HTTP endpoint uses a
live client while tests replay fixtures.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import nvd_client, scoring
from core import sync as core_sync
from core.sync import FetchFn

from ..config import get_settings
from ..models import RiskSnapshot, SyncRun, SyncStatus, Vendor
from . import alerts_service, scoring_service
from .exceptions import ValidationError
from .store import SqlAlchemyVulnStore


def build_live_fetch(
    *, config: nvd_client.NVDConfig | None = None, now: datetime | None = None
) -> FetchFn:
    """A fetch(vendor, query_type) that pulls live from NVD using the system key."""
    config = config or nvd_client.NVDConfig(api_key=get_settings().nvd_api_key)
    session = nvd_client.make_session(config)
    now = now or datetime.now(UTC)

    def fetch(vendor: dict, query_type: str) -> dict:
        return nvd_client.fetch_query(
            vendor["cpe_prefix"], query_type, config=config, session=session, now=now,
            log=lambda *a, **k: None,
        )

    return fetch


def get_vendor_fetcher() -> FetchFn:
    """FastAPI dependency (overridden in tests to replay fixtures)."""
    return build_live_fetch()


def sync_vendor(
    db: Session,
    org_id: int,
    vendor: Vendor,
    *,
    fetch: FetchFn,
    now: datetime | None = None,
) -> SyncRun:
    now = now or datetime.now(UTC)
    if not vendor.cpe_prefix:
        raise ValidationError("Vendor has no CPE mapping; onboard it before syncing")

    run = SyncRun(org_id=org_id, mode="live", status=SyncStatus.running)
    db.add(run)
    db.flush()

    store = SqlAlchemyVulnStore(db, org_id)
    prepared = [
        {
            "vendor_name": vendor.name,
            "cpe_prefix": vendor.cpe_prefix,
            "business": {},
            "match_method": "virtual_match",
        }
    ]
    # The prior snapshot (before this run) is what alerts diff against.
    prev_snapshot = db.scalar(
        select(RiskSnapshot)
        .where(RiskSnapshot.vendor_id == vendor.id)
        .order_by(RiskSnapshot.captured_at.desc())
    )

    result = core_sync.ingest(store, prepared, fetch=fetch, log=lambda *a, **k: None)

    vendor.last_synced_at = now
    new_snapshot: RiskSnapshot | None = None
    if result.succeeded:
        cves = scoring_service.cves_for_vendor(db, vendor.id)
        assessment = scoring.assess(scoring_service.vendor_to_dict(vendor), cves)
        new_snapshot = RiskSnapshot(
            vendor_id=vendor.id,
            tier=assessment["tier"],
            threat_band=assessment["threat_band"],
            exposure_band=assessment["exposure_band"],
            max_cvss=assessment["max_cvss"],
            cve_count=assessment["cve_count"],
            kev_count=assessment["kev_count"],
            captured_at=now,
        )
        db.add(new_snapshot)

    run.status = SyncStatus(result.status)
    run.completed_at = now
    run.vendors_attempted = result.attempted
    run.vendors_succeeded = result.succeeded
    run.cves_upserted = result.cves_upserted
    run.error_detail = "; ".join(result.errors) or None
    db.commit()
    db.refresh(run)

    # Evaluate alert rules against the tier/KEV delta (opt-in per org).
    if new_snapshot is not None:
        alerts_service.evaluate_on_sync(db, org_id, vendor, prev_snapshot, new_snapshot)
    return run
