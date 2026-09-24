"""Name-to-CPE onboarding: search the NVD CPE dictionary for a vendor name.

A user types a product/vendor name; this returns distinct CPE products (each with
the ``prefix`` used for CVE sync) so they pick a real mapping instead of hand-
typing a ``cpe:2.3:...`` string. The NVD fetch is an injected port so the logic
is unit-tested offline; the API builds a live fetch keyed on the org's NVD key.
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from core import nvd_client, parser
from core.nvd_client import NVDConfig, VendorFetchError

from ..config import get_settings
from . import integration_service
from .exceptions import UnavailableError
from .nvd_limits import NvdThrottle, RateLimitBusy

# keyword -> raw NVD CPE-search payload.
FetchCpesFn = Callable[[str], dict]

_noop = lambda *a, **k: None  # noqa: E731 — silence the client's logging

MIN_KEYWORD = 2
MAX_CANDIDATES = 25


def build_live_cpe_fetch(
    db: Session,
    org_id: int,
    *,
    throttle_factory: Callable[..., NvdThrottle] = NvdThrottle,
) -> FetchCpesFn:
    """A fetch(keyword) that queries NVD live using the org key (else system key),
    through the shared per-key bucket. A starved bucket or an NVD failure is a 503
    the user can act on ("try again"), not a 500."""
    api_key = integration_service.resolve_nvd_api_key(db, org_id) or get_settings().nvd_api_key
    config = NVDConfig(api_key=api_key)
    session = nvd_client.make_session(config)
    throttle = throttle_factory(api_key, max_wait=get_settings().nvd_interactive_max_wait_seconds)

    def fetch(keyword: str) -> dict:
        try:
            throttle.wait()
            return nvd_client.search_cpes(keyword, config=config, session=session, log=_noop)
        except RateLimitBusy as exc:
            raise UnavailableError("NVD is busy right now (rate limit). Try again in a moment.") from exc
        except VendorFetchError as exc:
            raise UnavailableError("NVD search is unavailable right now. Try again in a moment.") from exc

    return fetch


def search_products(keyword: str, *, fetch_cpes: FetchCpesFn) -> list[dict]:
    """Return distinct CPE product candidates for ``keyword`` (empty if too short)."""
    keyword = keyword.strip()
    if len(keyword) < MIN_KEYWORD:
        return []
    payload = fetch_cpes(keyword)
    products = parser.parse_cpe_products(payload)
    return parser.group_cpe_products(products)[:MAX_CANDIDATES]
