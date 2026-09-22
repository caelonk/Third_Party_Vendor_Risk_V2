"""Engine-agnostic ingest orchestration.

Extracted from the demo's ``pipeline.ingest`` so that exactly one implementation
of the ingest integrity rules is shared by the offline dev seed (SQLite) and the
production worker (SQLAlchemy/Postgres). It depends only on two injected ports:

* a :class:`VulnStore` — how rows are written (idempotent upserts);
* a ``fetch`` callable — how a vendor's raw NVD payloads are obtained
  (live HTTP, replayed fixtures, or a stubbed test double).

Integrity rules preserved here:

* One bad vendor never aborts the run: a :class:`~core.nvd_client.VendorFetchError`
  is caught, recorded, and the run continues (ending ``partial``).
* A partial/failed fetch never overwrites prior good rows: an already-mapped
  vendor is *not* downgraded to "Not Assessed".
* Missing CVSS stays ``None`` (the parser guarantees it); nothing here coerces 0.0.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from . import parser
from .nvd_client import QUERY_TYPES, VendorFetchError

# fetch(vendor, query_type) -> NVD-shaped payload. Raises VendorFetchError on
# failure. Receives the whole vendor dict so a live implementation can read
# ``cpe_prefix`` while an offline one can key fixtures on ``vendor_name``.
FetchFn = Callable[[dict, str], dict]


class VulnStore(Protocol):
    """Storage port. Implementations must make every write idempotent."""

    def upsert_vendor(self, vendor: dict) -> int:
        """Insert/update a vendor row; return its id."""

    def upsert_vulnerability(self, record: dict) -> None:
        """Insert/update one normalized CVE record."""

    def link_vendor_vulnerability(self, vendor_id: int, cve_id: str) -> None:
        """Idempotently link a vendor to a CVE."""

    def vendor_is_mapped(self, vendor_name: str) -> bool | None:
        """True/False if the vendor exists, else None when it is unknown."""

    def commit(self) -> None:
        """Flush the current vendor's writes."""


@dataclass
class IngestResult:
    attempted: int = 0
    succeeded: int = 0
    cves_upserted: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.succeeded == 0:
            return "failed"
        if self.succeeded < self.attempted:
            return "partial"
        return "success"


def ingest(
    store: VulnStore,
    vendors: list[dict],
    *,
    fetch: FetchFn,
    query_types: tuple[str, ...] = QUERY_TYPES,
    log=print,
) -> IngestResult:
    """Fetch, parse, and store CVEs for each vendor.

    Each ``vendor`` is ``{"vendor_name", "cpe_prefix", "business": {...},
    "match_method"?}``. ``business`` carries the org's contract fields and is
    written verbatim onto the vendor row.
    """
    result = IngestResult()
    cves_seen: set[str] = set()

    for vendor in vendors:
        name = vendor["vendor_name"]
        prefix = vendor["cpe_prefix"]
        business = vendor.get("business") or {}
        match_method = vendor.get("match_method", "virtual_match")
        result.attempted += 1
        log(f"[{result.attempted}/{len(vendors)}] {name}  ({prefix})")

        try:
            payloads = {qt: fetch(vendor, qt) for qt in query_types}
        except VendorFetchError as exc:
            log(f"    FAILED: {exc}")
            result.errors.append(f"{name}: {exc}")
            _record_unassessed(store, name, business, log=log)
            continue

        records: list[dict] = []
        for payload in payloads.values():
            records.extend(parser.parse_response(payload))

        vendor_id = store.upsert_vendor(
            {"vendor_name": name, "is_mapped": 1, "match_method": match_method, **business}
        )
        linked = 0
        kev = 0
        for record in records:
            store.upsert_vulnerability(record)
            store.link_vendor_vulnerability(vendor_id, record["cve_id"])
            cves_seen.add(record["cve_id"])
            linked += 1
            kev += int(record.get("is_kev") or 0)
        store.commit()
        result.succeeded += 1
        log(f"    stored {linked} CVE links ({kev} KEV)")

    result.cves_upserted = len(cves_seen)
    return result


def _record_unassessed(store: VulnStore, name: str, business: dict, *, log) -> None:
    """Mark a failed/unmapped vendor 'Not Assessed' — but never overwrite prior
    good data with an empty result (Integrity Rule 7)."""
    if store.vendor_is_mapped(name):
        log("    keeping prior good data (not downgrading to Not Assessed)")
        return
    store.upsert_vendor(
        {"vendor_name": name, "is_mapped": 0, "match_method": None, **business}
    )
    store.commit()
