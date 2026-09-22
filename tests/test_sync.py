"""Engine-agnostic tests for core.sync.ingest.

These drive the shared ingest orchestration with an in-memory fake store and a
stub fetch, so the integrity rules are verified without SQLite, Postgres, or the
network — the same logic the production worker runs.
"""
from core import sync
from core.nvd_client import VendorFetchError


class FakeStore:
    """In-memory VulnStore. Tracks vendor rows and vendor<->cve links."""

    def __init__(self):
        self.vendors: dict[str, dict] = {}
        self._ids: dict[str, int] = {}
        self.vulns: dict[str, dict] = {}
        self.links: set[tuple[int, str]] = set()
        self.commits = 0

    def upsert_vendor(self, vendor: dict) -> int:
        name = vendor["vendor_name"]
        self.vendors[name] = {**self.vendors.get(name, {}), **vendor}
        self._ids.setdefault(name, len(self._ids) + 1)
        return self._ids[name]

    def upsert_vulnerability(self, record: dict) -> None:
        self.vulns[record["cve_id"]] = record

    def link_vendor_vulnerability(self, vendor_id: int, cve_id: str) -> None:
        self.links.add((vendor_id, cve_id))

    def vendor_is_mapped(self, vendor_name: str):
        row = self.vendors.get(vendor_name)
        return None if row is None else bool(row.get("is_mapped"))

    def commit(self) -> None:
        self.commits += 1


def _payload(*cve_ids, kev=False):
    return {
        "vulnerabilities": [
            {"cve": {"id": cid, "cisaExploitAdd": "2023-01-01" if kev else None}}
            for cid in cve_ids
        ]
    }


def _vendor(name, prefix="cpe:2.3:a:x"):
    return {"vendor_name": name, "cpe_prefix": prefix, "business": {}}


def test_success_when_all_vendors_fetch():
    store = FakeStore()
    fetch = lambda vendor, qt: _payload("CVE-1")  # noqa: E731
    result = sync.ingest(store, [_vendor("A"), _vendor("B")], fetch=fetch, log=lambda *a, **k: None)
    assert result.status == "success"
    assert result.attempted == 2 and result.succeeded == 2
    assert store.vendors["A"]["is_mapped"] == 1


def test_partial_when_one_vendor_fails():
    store = FakeStore()

    def fetch(vendor, qt):
        if vendor["vendor_name"] == "B":
            raise VendorFetchError("boom")
        return _payload("CVE-1")

    result = sync.ingest(store, [_vendor("A"), _vendor("B")], fetch=fetch, log=lambda *a, **k: None)
    assert result.status == "partial"
    assert result.succeeded == 1
    assert any("B:" in e for e in result.errors)
    # B was unknown before, so it is recorded Not Assessed (is_mapped=0).
    assert store.vendors["B"]["is_mapped"] == 0


def test_failed_when_all_vendors_fail():
    store = FakeStore()

    def fetch(vendor, qt):
        raise VendorFetchError("boom")

    result = sync.ingest(store, [_vendor("A")], fetch=fetch, log=lambda *a, **k: None)
    assert result.status == "failed"


def test_prior_good_vendor_is_not_downgraded_on_failure():
    """Integrity Rule 7: a partial fetch never overwrites prior good rows."""
    store = FakeStore()
    store.upsert_vendor({"vendor_name": "A", "is_mapped": 1, "match_method": "virtual_match"})

    def fetch(vendor, qt):
        raise VendorFetchError("transient")

    sync.ingest(store, [_vendor("A")], fetch=fetch, log=lambda *a, **k: None)
    assert store.vendors["A"]["is_mapped"] == 1  # still mapped, not "Not Assessed"


def test_cves_upserted_is_deduplicated_across_vendors():
    store = FakeStore()
    fetch = lambda vendor, qt: _payload("CVE-SHARED")  # noqa: E731
    result = sync.ingest(store, [_vendor("A"), _vendor("B")], fetch=fetch, log=lambda *a, **k: None)
    assert result.cves_upserted == 1  # both vendors share the one CVE
    assert len(store.links) == 2       # but each vendor is linked to it
