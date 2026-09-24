"""One throttle for every NVD call: worker syncs, the Sync button, CPE search.

NVD enforces its rolling-window limit *per API key*, so every caller using a key
draws from the same Redis token bucket (app.workers.rate_limit). Priorities:

* interactive calls (Sync button, CPE search) and incremental syncs draw freely;
* backfills — a product's first, expensive pull — draw with a *reserve*, so they
  only proceed while the bucket holds more than a cushion and can never starve
  the others.

Without Redis (plain local dev on SQLite) the throttle degrades to the NVD
client's per-process pacing and says so once, instead of failing requests.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import redis as redis_lib
from redis.exceptions import RedisError

from ..config import get_settings
from ..workers.rate_limit import BucketSpec, RedisRateLimiter, bucket_id

log = logging.getLogger(__name__)
_warned_degraded = False


class RateLimitBusy(Exception):
    """The shared NVD budget stayed exhausted past the caller's wait cap."""


def spec_for(api_key: str | None) -> BucketSpec:
    """The bucket shape for a key: NVD's with-key or keyless rolling window."""
    s = get_settings()
    per_window = s.nvd_rate_with_key_per_window if api_key else s.nvd_rate_keyless_per_window
    return BucketSpec.from_window(per_window, s.nvd_rate_window_seconds)


def backfill_reserve(spec: BucketSpec) -> float:
    """Tokens a backfill must leave in the bucket (e.g. 15 of 50, 2 of 5)."""
    return float(math.ceil(spec.capacity * get_settings().nvd_backfill_reserve_fraction))


class NvdThrottle:
    """Call :meth:`wait` before each NVD request made with ``api_key``."""

    def __init__(
        self,
        api_key: str | None,
        *,
        backfill: bool = False,
        max_wait: float | None = None,
        redis_client: Any = None,
    ) -> None:
        settings = get_settings()
        self.spec = spec_for(api_key)
        self.bucket = bucket_id(api_key)
        self.reserve = backfill_reserve(self.spec) if backfill else 0.0
        client = redis_client or redis_lib.from_url(
            settings.redis_url, socket_connect_timeout=2, socket_timeout=5
        )
        self._limiter = RedisRateLimiter(
            client, max_wait=max_wait if max_wait is not None else settings.nvd_rate_max_wait_seconds
        )
        self._degraded = False

    def wait(self) -> None:
        if self._degraded:
            return
        try:
            self._limiter.acquire(self.spec, self.bucket, reserve=self.reserve)
        except TimeoutError as exc:
            raise RateLimitBusy(str(exc)) from exc
        except RedisError as exc:
            global _warned_degraded
            self._degraded = True
            if not _warned_degraded:
                _warned_degraded = True
                log.warning(
                    "NVD shared rate limit unavailable (%s); falling back to "
                    "per-process pacing only",
                    type(exc).__name__,
                )
