"""NVD 2.0 REST client: rate limiting, pagination, and retry/backoff.

Adapted from the demo's keyless client. The demo's hard caps are now
configuration (:class:`NVDConfig`): the results-per-page, page limit, recent
window, and pacing are arguments, and an ``api_key`` raises the rate limit.

* Keyless: 5 requests / rolling 30s  -> default pacing 6s, no key header.
* With key: 50 requests / rolling 30s -> default pacing 0.6s, ``apiKey`` header.

Pacing is still applied before *every* request (including retries); a global
Redis token bucket keyed by API key enforces the limit across workers at the
service layer. A single bad vendor raises :class:`VendorFetchError`; callers
catch it, mark the run ``partial``, and move on — one bad vendor never aborts a
run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests

BASE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
CPE_URL = "https://services.nvd.nist.gov/rest/json/cpes/2.0"
RETRY_STATUS = {403, 429, 503}

# CPE keyword search: one page of this size surfaces the distinct products for a
# name without paginating a product's every version.
CPE_RESULTS_PER_PAGE = 500

# NVD API ceilings (not demo caps): 2000 results/page, 120-day date ranges.
MAX_RESULTS_PER_PAGE = 2000
MAX_WINDOW_DAYS = 120

# Pacing floors, seconds between requests (NVD's documented rolling-window limits).
PACE_WITH_KEY = 0.6
PACE_KEYLESS = 6.0

QUERY_TYPES = ("recent", "kev")


class VendorFetchError(Exception):
    """Raised when a vendor query cannot be completed after retries."""


@dataclass(frozen=True)
class NVDConfig:
    """Tunable client behavior. Defaults fetch *all* pages (no demo cap)."""

    api_key: str | None = None
    results_per_page: int = MAX_RESULTS_PER_PAGE
    max_pages: int | None = None          # None -> paginate until exhausted
    recent_window_days: int = MAX_WINDOW_DAYS
    retry_backoff: tuple[int, ...] = (7, 15, 30)
    pace_seconds: float | None = None     # None -> derived from api_key

    @property
    def pacing(self) -> float:
        if self.pace_seconds is not None:
            return self.pace_seconds
        return PACE_WITH_KEY if self.api_key else PACE_KEYLESS


def make_session(config: NVDConfig | None = None) -> requests.Session:
    config = config or NVDConfig()
    session = requests.Session()
    session.headers.update({"User-Agent": "vendor-risk/1.0"})
    if config.api_key:
        session.headers.update({"apiKey": config.api_key})
    return session


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000")


def build_params(
    prefix: str,
    query_type: str,
    now: datetime,
    config: NVDConfig,
    *,
    last_mod_start: datetime | None = None,
) -> dict:
    """Query params for a vendor.

    ``recent`` fetches by publication date over the configured window; ``kev``
    fetches all known-exploited CVEs for the prefix. When ``last_mod_start`` is
    given, ``recent`` becomes an incremental pull keyed on last-modified date
    (catching both new CVEs and CVSS/KEV changes on existing ones) — the basis
    for scheduled incremental sync. ``noRejected``/``hasKev`` are valueless
    flags (the API accepts the empty-string form ``requests`` emits).
    """
    if query_type == "recent":
        params = {
            "virtualMatchString": prefix,
            "noRejected": "",
            "resultsPerPage": config.results_per_page,
        }
        if last_mod_start is not None:
            params["lastModStartDate"] = _iso(last_mod_start)
            params["lastModEndDate"] = _iso(now)
        else:
            params["pubStartDate"] = _iso(now - timedelta(days=config.recent_window_days))
            params["pubEndDate"] = _iso(now)
        return params
    if query_type == "kev":
        return {
            "virtualMatchString": prefix,
            "hasKev": "",
            "resultsPerPage": config.results_per_page,
        }
    raise ValueError(f"unknown query_type: {query_type!r}")


def _get(session, params, config: NVDConfig, *, url: str = BASE_URL, log, sleeper) -> dict:
    """One GET, paced and retried. Returns parsed JSON or raises VendorFetchError."""
    sleeper(config.pacing)
    last_error = None
    for backoff in (None, *config.retry_backoff):
        if backoff is not None:
            log(f"      retryable failure ({last_error}); backing off {backoff}s")
            sleeper(backoff)
        try:
            resp = session.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in RETRY_STATUS:
            last_error = f"HTTP {resp.status_code}"
            continue
        raise VendorFetchError(f"HTTP {resp.status_code} (non-retryable)")
    raise VendorFetchError(f"gave up after retries: {last_error}")


def fetch_query(
    prefix: str,
    query_type: str,
    *,
    config: NVDConfig | None = None,
    session=None,
    now: datetime | None = None,
    last_mod_start: datetime | None = None,
    log=print,
    sleeper=time.sleep,
) -> dict:
    """Fetch one vendor query (``recent`` or ``kev``), paginated.

    Returns a single merged NVD-shaped payload whose ``vulnerabilities`` list
    holds every CVE across the fetched pages.
    """
    config = config or NVDConfig()
    session = session or make_session(config)
    now = now or datetime.now(UTC)
    base_params = build_params(prefix, query_type, now, config, last_mod_start=last_mod_start)

    merged: dict | None = None
    start_index = 0
    pages = 0
    while True:
        payload = _get(
            session, dict(base_params, startIndex=start_index), config, log=log, sleeper=sleeper
        )
        vulns = payload.get("vulnerabilities") or []
        if merged is None:
            merged = payload
        else:
            merged.setdefault("vulnerabilities", []).extend(vulns)
        total = int(payload.get("totalResults", 0) or 0)
        pages += 1
        start_index += config.results_per_page
        log(f"      page {pages}: +{len(vulns)} CVEs (available {total})")
        capped = config.max_pages is not None and pages >= config.max_pages
        if capped or start_index >= total or not vulns:
            break

    merged = merged or {"vulnerabilities": []}
    merged["startIndex"] = 0
    merged["resultsPerPage"] = len(merged.get("vulnerabilities") or [])
    return merged


def search_cpes(
    keyword: str,
    *,
    config: NVDConfig | None = None,
    session=None,
    results_per_page: int = CPE_RESULTS_PER_PAGE,
    log=print,
    sleeper=time.sleep,
) -> dict:
    """Search the NVD CPE dictionary by keyword (product/vendor name).

    Returns the raw NVD CPE-search payload (``products`` list). One page only —
    enough to surface the distinct products for a name; :func:`core.parser`
    collapses the version rows. Raises :class:`VendorFetchError` on failure.
    """
    config = config or NVDConfig()
    session = session or make_session(config)
    params = {"keywordSearch": keyword, "resultsPerPage": results_per_page, "startIndex": 0}
    return _get(session, params, config, url=CPE_URL, log=log, sleeper=sleeper)
