"""Dev seed pipeline: ingest (offline fixtures or keyless live) -> score -> HTML.

    python -m seed.pipeline            # keyless live NVD pull (no API key)
    python -m seed.pipeline --offline  # replay saved fixtures, zero network
    python -m seed.pipeline --vendor Fortinet   # refresh a single vendor

This is a **developer** tool. It drives :func:`core.sync.ingest` with a
SQLite-backed store so the shared ingest logic is exercised exactly as the
production worker exercises it (only the store and fetch ports differ). The
synthetic business-data generator lives here and is for local seeding only.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core import nvd_client, sync

from . import report_html
from . import sqlite_store as db

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
VENDORS_FILE = CONFIG_DIR / "vendors.yml"
BUSINESS_FILE = CONFIG_DIR / "business_context.csv"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
DB_PATH = DATA_DIR / "risk.db"


# --------------------------------------------------------------------------- #
# Config readers                                                               #
# --------------------------------------------------------------------------- #
def read_vendors_yml(path: Path) -> list[dict]:
    """Hand-rolled reader for the flat vendors.yml (no PyYAML dependency).

    The file is a list of ``- vendor: <name>`` / ``cpe: [<prefixes>]`` pairs.
    The bracketed cpe list is read with stdlib ``json.loads`` (split on the
    first colon only, so the internal colons of a CPE string survive).
    """
    vendors: list[dict] = []
    current: dict | None = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- vendor:"):
            if current:
                vendors.append(current)
            current = {"vendor_name": line.split(":", 1)[1].strip(), "cpe": []}
        elif line.startswith("cpe:") and current is not None:
            current["cpe"] = json.loads(line.split(":", 1)[1].strip())
    if current:
        vendors.append(current)
    return vendors


def load_business_context(path: Path) -> dict[str, dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        return {row["vendor_name"]: row for row in csv.DictReader(f)}


def _business_fields(biz: dict) -> dict:
    acv = biz.get("annual_contract_value")
    return {
        "annual_contract_value": float(acv) if acv not in (None, "") else None,
        "data_sensitivity": biz.get("data_sensitivity"),
        "business_criticality": biz.get("business_criticality"),
        "contract_renewal_date": biz.get("contract_renewal_date"),
    }


# --------------------------------------------------------------------------- #
# Synthetic business-data generator (deterministic, seed=42) — dev only        #
# --------------------------------------------------------------------------- #
# Designed spread so all four exposure bands appear and 3-5 vendors renew within
# 90 days of the reference date. Values are FABRICATED — labeled synthetic
# everywhere they surface.
_BUSINESS_PROFILES = [
    ("Microsoft",         "regulated",    "high",   (600_000, 900_000), False),
    ("Oracle",            "confidential", "high",   (520_000, 700_000), True),
    ("Atlassian",         "internal",     "medium", (30_000, 60_000),   True),
    ("Cisco",             "confidential", "high",   (200_000, 400_000), False),
    ("VMware",            "internal",     "high",   (120_000, 180_000), False),
    ("Adobe",             "internal",     "medium", (40_000, 80_000),   False),
    ("Fortinet",          "confidential", "high",   (150_000, 250_000), True),
    ("Citrix",            "internal",     "medium", (15_000, 24_000),   False),
    ("Progress Software", "regulated",    "high",   (300_000, 480_000), True),
    ("GitLab",            "internal",     "medium", (26_000, 50_000),   False),
    ("Elastic",           "public",       "low",    (5_000, 20_000),    False),
    ("Zoom",              "internal",     "low",    (20_000, 24_000),   False),
]


def generate_business_context(path: Path) -> None:
    rng = random.Random(42)
    rows = []
    for name, sensitivity, criticality, (lo, hi), soon in _BUSINESS_PROFILES:
        acv = rng.randint(lo // 1000, hi // 1000) * 1000
        offset = rng.randint(7, 85) if soon else rng.randint(100, 350)
        renewal = report_html.REFERENCE_DATE + timedelta(days=offset)
        rows.append({
            "vendor_name": name,
            "annual_contract_value": acv,
            "data_sensitivity": sensitivity,
            "business_criticality": criticality,
            "contract_renewal_date": renewal.isoformat(),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def ensure_business_context(path: Path, *, log=print) -> None:
    if not Path(path).exists():
        log("business_context.csv missing - generating synthetic data (seed=42)")
        generate_business_context(Path(path))


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _slug(vendor_name: str) -> str:
    return vendor_name.lower().replace(" ", "_")


def save_fixtures(fixtures_dir: Path, vendor_name: str, payloads: dict) -> None:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    for query_type, payload in payloads.items():
        path = fixtures_dir / f"{_slug(vendor_name)}_{query_type}.json"
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load_fixtures(fixtures_dir: Path, vendor_name: str) -> tuple[dict, int]:
    """Return (payloads-by-querytype, number_of_fixture_files_present)."""
    payloads: dict = {}
    present = 0
    for query_type in nvd_client.QUERY_TYPES:
        path = fixtures_dir / f"{_slug(vendor_name)}_{query_type}.json"
        if path.exists():
            payloads[query_type] = json.loads(path.read_text(encoding="utf-8"))
            present += 1
        else:
            payloads[query_type] = {"vulnerabilities": []}
    return payloads, present


# --------------------------------------------------------------------------- #
# Fetch ports (offline / live), consumed by core.sync.ingest                   #
# --------------------------------------------------------------------------- #
def _offline_fetch(fixtures_dir: Path):
    """Return a fetch(vendor, query_type) that replays saved fixtures."""
    cache: dict[str, dict] = {}

    def fetch(vendor: dict, query_type: str) -> dict:
        name = vendor["vendor_name"]
        if name not in cache:
            payloads, present = load_fixtures(fixtures_dir, name)
            if present == 0:
                raise nvd_client.VendorFetchError("no fixture present (offline)")
            cache[name] = payloads
        return cache[name][query_type]

    return fetch


def _live_fetch(fixtures_dir: Path, *, session, config, now, log, sleeper):
    """Return a fetch(vendor, query_type) that pulls from NVD and saves fixtures."""
    saved: dict[str, dict] = {}

    def fetch(vendor: dict, query_type: str) -> dict:
        name = vendor["vendor_name"]
        prefix = vendor["cpe_prefix"]
        log(f"    query: {query_type}")
        payload = nvd_client.fetch_query(
            prefix, query_type, config=config, session=session, now=now, log=log, sleeper=sleeper
        )
        saved.setdefault(name, {})[query_type] = payload
        if len(saved[name]) == len(nvd_client.QUERY_TYPES):
            save_fixtures(fixtures_dir, name, saved[name])
        return payload

    return fetch


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #
def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _prepare_vendors(vendors: list[dict], business: dict) -> list[dict]:
    prepared = []
    for v in vendors:
        name = v["vendor_name"]
        prepared.append({
            "vendor_name": name,
            "cpe_prefix": v["cpe"][0],
            "match_method": "virtual_match",
            "business": _business_fields(business.get(name, {})),
        })
    return prepared


def run(
    *,
    offline: bool = False,
    vendor_filter: str | None = None,
    db_path: Path = DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    fixtures_dir: Path = FIXTURES_DIR,
    business_file: Path = BUSINESS_FILE,
    vendors_file: Path = VENDORS_FILE,
    log=print,
    sleeper=time.sleep,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    mode = "offline" if offline else "live"
    log(f"=== Vendor Risk dev seed - {mode} run ===")

    ensure_business_context(business_file, log=log)
    vendors = read_vendors_yml(vendors_file)
    if vendor_filter:
        vendors = [v for v in vendors if v["vendor_name"].lower() == vendor_filter.lower()]
        if not vendors:
            raise SystemExit(f"Unknown vendor: {vendor_filter!r}")
    business = load_business_context(business_file)
    prepared = _prepare_vendors(vendors, business)

    conn = db.connect(db_path)
    db.init_schema(conn)
    run_id = db.start_run(conn, mode, _iso(now))

    if offline:
        fetch = _offline_fetch(fixtures_dir)
    else:
        fetch = _live_fetch(
            fixtures_dir,
            session=nvd_client.make_session(),
            config=nvd_client.NVDConfig(),
            now=now,
            log=log,
            sleeper=sleeper,
        )

    store = db.SqliteStore(conn)
    result = sync.ingest(store, prepared, fetch=fetch, log=log)

    db.finish_run(
        conn, run_id,
        status=result.status,
        completed_at=_iso(datetime.now(UTC)),
        vendors_attempted=result.attempted,
        vendors_succeeded=result.succeeded,
        cves_upserted=result.cves_upserted,
        error_detail="; ".join(result.errors) or None,
    )

    run_row = db.get_latest_run(conn)
    paths = report_html.render(conn, run=run_row, output_dir=output_dir)
    counts = db.data_table_counts(conn)
    conn.close()

    log(
        f"\n=== done: status={result.status} | vendors {result.succeeded}/{result.attempted} "
        f"| CVEs stored={counts['vulnerabilities']} | watchlist={paths['watchlist_count']} ==="
    )
    log(f"dashboard: {paths['dashboard']}")
    return {"status": result.status, "paths": paths, "result": result, "counts": counts}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Vendor risk dev seed pipeline")
    ap.add_argument("--offline", action="store_true", help="Replay saved fixtures; no network")
    ap.add_argument("--vendor", metavar="NAME", help="Refresh a single vendor by name")
    args = ap.parse_args(argv)
    run(offline=args.offline, vendor_filter=args.vendor)


if __name__ == "__main__":
    main()
