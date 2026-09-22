"""A SQLAlchemy-backed :class:`core.sync.VulnStore` for on-demand/scheduled sync.

The web layer drives the *same* ``core.sync.ingest`` orchestration the dev seed
uses; only the store differs. This store is **org-scoped**: it never creates
vendors (they are created via CRUD), it only marks the existing per-org vendor
mapped and links it to the shared, global CVE cache.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MatchMethod, Vendor, VendorVulnerability, Vulnerability
from .exceptions import NotFoundError


class SqlAlchemyVulnStore:
    def __init__(self, db: Session, org_id: int) -> None:
        self.db = db
        self.org_id = org_id
        # Per-batch dedup: the recent + kev payloads share CVEs, and the session
        # runs autoflush=False so merge() cannot see pending rows.
        self._seen_vulns: set[str] = set()
        self._linked: set[tuple[int, str]] = set()

    def _vendor(self, name: str) -> Vendor | None:
        return self.db.scalar(
            select(Vendor).where(Vendor.org_id == self.org_id, Vendor.name == name)
        )

    def upsert_vendor(self, vendor: dict) -> int:
        v = self._vendor(vendor["vendor_name"])
        if v is None:
            raise NotFoundError(f"Vendor {vendor['vendor_name']!r} not found in org")
        v.is_mapped = bool(vendor.get("is_mapped", 1))
        method = vendor.get("match_method")
        v.match_method = MatchMethod(method) if method else None
        self.db.flush()
        return v.id

    def upsert_vulnerability(self, record: dict) -> None:
        # Global cache, deduplicated by CVE id across all tenants. merge() is a
        # dialect-agnostic upsert-by-PK. cvss_score stays None, never 0.0.
        if record["cve_id"] in self._seen_vulns:
            return
        self._seen_vulns.add(record["cve_id"])
        self.db.merge(
            Vulnerability(
                cve_id=record["cve_id"],
                cvss_score=record.get("cvss_score"),
                cvss_version=record.get("cvss_version"),
                cvss_severity=record.get("cvss_severity"),
                is_kev=bool(record.get("is_kev")),
                kev_date_added=record.get("kev_date_added"),
                kev_due_date=record.get("kev_due_date"),
                published_date=record.get("published_date"),
                vuln_status=record.get("vuln_status"),
                description=record.get("description"),
                updated_at=datetime.now(UTC),
            )
        )

    def link_vendor_vulnerability(self, vendor_id: int, cve_id: str) -> None:
        key = (vendor_id, cve_id)
        if key in self._linked:
            return
        self._linked.add(key)
        # merge() keeps cross-run re-sync idempotent (finds an existing DB row).
        self.db.merge(VendorVulnerability(vendor_id=vendor_id, cve_id=cve_id))

    def vendor_is_mapped(self, vendor_name: str) -> bool | None:
        v = self._vendor(vendor_name)
        return None if v is None else v.is_mapped

    def commit(self) -> None:
        self.db.commit()
