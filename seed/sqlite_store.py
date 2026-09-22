"""SQLite schema and idempotent upserts for the dev seed (stdlib ``sqlite3``).

Ported from the demo's ``db.py``. Every write is an ``INSERT ... ON CONFLICT ...
DO UPDATE`` (or ``DO NOTHING`` for the junction table), so running the seed twice
never duplicates rows. We never bulk-DELETE before an ingest: a vendor whose
fetch fails keeps its prior good rows (Integrity Rule 7).

:class:`SqliteStore` adapts these functions to the :class:`core.sync.VulnStore`
protocol so the shared ingest orchestration drives SQLite unchanged.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id INTEGER PRIMARY KEY,
    vendor_name TEXT NOT NULL UNIQUE,
    annual_contract_value REAL,
    data_sensitivity TEXT,      -- public|internal|confidential|regulated
    business_criticality TEXT,  -- low|medium|high
    contract_renewal_date TEXT, -- ISO date
    is_mapped INTEGER NOT NULL DEFAULT 0,
    match_method TEXT           -- 'virtual_match' | 'keyword'
);

CREATE TABLE IF NOT EXISTS vulnerabilities (
    cve_id TEXT PRIMARY KEY,
    cvss_score REAL,            -- NULLABLE. Never coalesced to 0.0.
    cvss_version TEXT,          -- '4.0'|'3.1'|'3.0'|'2.0'|NULL
    cvss_severity TEXT,
    is_kev INTEGER NOT NULL DEFAULT 0,
    kev_date_added TEXT,
    kev_due_date TEXT,
    published_date TEXT,
    vuln_status TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS vendor_vulnerabilities (
    vendor_id INTEGER NOT NULL REFERENCES vendors(vendor_id),
    cve_id TEXT NOT NULL REFERENCES vulnerabilities(cve_id),
    PRIMARY KEY (vendor_id, cve_id)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id INTEGER PRIMARY KEY,
    started_at TEXT, completed_at TEXT,
    status TEXT,                -- running|success|partial|failed
    mode TEXT,                  -- live|offline
    vendors_attempted INTEGER, vendors_succeeded INTEGER,
    cves_upserted INTEGER, error_detail TEXT
);
"""

DATA_TABLES = ("vendors", "vulnerabilities", "vendor_vulnerabilities")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign keys on and dict-like rows."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# Writes                                                                       #
# --------------------------------------------------------------------------- #
def upsert_vendor(conn: sqlite3.Connection, vendor: dict) -> int:
    """Insert or update one vendor row; return its vendor_id."""
    conn.execute(
        """
        INSERT INTO vendors (
            vendor_name, annual_contract_value, data_sensitivity,
            business_criticality, contract_renewal_date, is_mapped, match_method
        ) VALUES (
            :vendor_name, :annual_contract_value, :data_sensitivity,
            :business_criticality, :contract_renewal_date, :is_mapped, :match_method
        )
        ON CONFLICT(vendor_name) DO UPDATE SET
            annual_contract_value = excluded.annual_contract_value,
            data_sensitivity      = excluded.data_sensitivity,
            business_criticality  = excluded.business_criticality,
            contract_renewal_date = excluded.contract_renewal_date,
            is_mapped             = excluded.is_mapped,
            match_method          = excluded.match_method
        """,
        {
            "vendor_name": vendor["vendor_name"],
            "annual_contract_value": vendor.get("annual_contract_value"),
            "data_sensitivity": vendor.get("data_sensitivity"),
            "business_criticality": vendor.get("business_criticality"),
            "contract_renewal_date": vendor.get("contract_renewal_date"),
            "is_mapped": int(vendor.get("is_mapped", 0)),
            "match_method": vendor.get("match_method"),
        },
    )
    row = conn.execute(
        "SELECT vendor_id FROM vendors WHERE vendor_name = ?",
        (vendor["vendor_name"],),
    ).fetchone()
    return int(row["vendor_id"])


def upsert_vulnerability(conn: sqlite3.Connection, v: dict) -> None:
    """Insert or update one normalized CVE record (see parser.parse_cve)."""
    conn.execute(
        """
        INSERT INTO vulnerabilities (
            cve_id, cvss_score, cvss_version, cvss_severity, is_kev,
            kev_date_added, kev_due_date, published_date, vuln_status, description
        ) VALUES (
            :cve_id, :cvss_score, :cvss_version, :cvss_severity, :is_kev,
            :kev_date_added, :kev_due_date, :published_date, :vuln_status, :description
        )
        ON CONFLICT(cve_id) DO UPDATE SET
            cvss_score     = excluded.cvss_score,
            cvss_version   = excluded.cvss_version,
            cvss_severity  = excluded.cvss_severity,
            is_kev         = excluded.is_kev,
            kev_date_added = excluded.kev_date_added,
            kev_due_date   = excluded.kev_due_date,
            published_date = excluded.published_date,
            vuln_status    = excluded.vuln_status,
            description    = excluded.description
        """,
        {
            "cve_id": v["cve_id"],
            "cvss_score": v.get("cvss_score"),  # may be None — never 0.0
            "cvss_version": v.get("cvss_version"),
            "cvss_severity": v.get("cvss_severity"),
            "is_kev": int(v.get("is_kev", 0)),
            "kev_date_added": v.get("kev_date_added"),
            "kev_due_date": v.get("kev_due_date"),
            "published_date": v.get("published_date"),
            "vuln_status": v.get("vuln_status"),
            "description": v.get("description"),
        },
    )


def link_vendor_vulnerability(conn: sqlite3.Connection, vendor_id: int, cve_id: str) -> None:
    conn.execute(
        """
        INSERT INTO vendor_vulnerabilities (vendor_id, cve_id)
        VALUES (?, ?)
        ON CONFLICT(vendor_id, cve_id) DO NOTHING
        """,
        (vendor_id, cve_id),
    )


def vendor_is_mapped(conn: sqlite3.Connection, vendor_name: str) -> bool | None:
    """True/False if the vendor row exists, else None when it is unknown."""
    row = conn.execute(
        "SELECT is_mapped FROM vendors WHERE vendor_name = ?", (vendor_name,)
    ).fetchone()
    return None if row is None else bool(row["is_mapped"])


# --------------------------------------------------------------------------- #
# Ingest-run lifecycle                                                         #
# --------------------------------------------------------------------------- #
def start_run(conn: sqlite3.Connection, mode: str, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO ingest_runs (started_at, status, mode) VALUES (?, 'running', ?)",
        (started_at, mode),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    completed_at: str,
    vendors_attempted: int,
    vendors_succeeded: int,
    cves_upserted: int,
    error_detail: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ingest_runs SET
            completed_at = ?, status = ?, vendors_attempted = ?,
            vendors_succeeded = ?, cves_upserted = ?, error_detail = ?
        WHERE run_id = ?
        """,
        (
            completed_at, status, vendors_attempted,
            vendors_succeeded, cves_upserted, error_detail, run_id,
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Reads (for scoring + reporting)                                              #
# --------------------------------------------------------------------------- #
def get_all_vendors(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM vendors ORDER BY vendor_name").fetchall()
    return [dict(r) for r in rows]


def get_cves_for_vendor(conn: sqlite3.Connection, vendor_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT v.* FROM vulnerabilities v
        JOIN vendor_vulnerabilities vv ON vv.cve_id = v.cve_id
        WHERE vv.vendor_id = ?
        """,
        (vendor_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    # table is only ever passed a literal from DATA_TABLES / known constants.
    return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])


def data_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {t: count_rows(conn, t) for t in DATA_TABLES}


def count_unscored(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM vulnerabilities WHERE cvss_score IS NULL"
        ).fetchone()["n"]
    )


def get_latest_run(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ingest_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# core.sync.VulnStore adapter                                                  #
# --------------------------------------------------------------------------- #
class SqliteStore:
    """Bind a SQLite connection to the :class:`core.sync.VulnStore` protocol."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_vendor(self, vendor: dict) -> int:
        return upsert_vendor(self.conn, vendor)

    def upsert_vulnerability(self, record: dict) -> None:
        upsert_vulnerability(self.conn, record)

    def link_vendor_vulnerability(self, vendor_id: int, cve_id: str) -> None:
        link_vendor_vulnerability(self.conn, vendor_id, cve_id)

    def vendor_is_mapped(self, vendor_name: str) -> bool | None:
        return vendor_is_mapped(self.conn, vendor_name)

    def commit(self) -> None:
        self.conn.commit()
