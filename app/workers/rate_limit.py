"""Distributed token-bucket rate limiter (Redis-backed) for NVD API calls.

NVD enforces a rolling-window request cap *per API key* (50 requests / 30 s with
a key, 5 / 30 s without). Several Celery workers may sync different CPE prefixes
with the same key at once, so the limit has to hold *across* workers — a local
``time.sleep`` in one process is not enough. This module keeps one token bucket
per key in Redis, refills it continuously, and blocks in :meth:`acquire` until a
token is free.

The refill/consume arithmetic is a pure function (:class:`TokenBucket`) and is
unit-tested with a fake clock. The Redis layer applies that same arithmetic
atomically via a Lua script, so two workers cannot double-spend a token; that
path is exercised live against Redis in Docker/CI.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketSpec:
    """A bucket's shape: burst ``capacity`` and steady ``refill`` per second."""

    capacity: float
    refill_per_sec: float

    @classmethod
    def from_window(cls, per_window: int, window_seconds: float) -> BucketSpec:
        """Build a spec from a rolling-window limit (e.g. 50 requests / 30 s)."""
        rate = per_window / window_seconds if window_seconds > 0 else 0.0
        return cls(capacity=float(per_window), refill_per_sec=rate)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    tokens: float        # tokens remaining after this attempt
    retry_after: float   # seconds until a token frees up (0.0 when allowed)


class TokenBucket:
    """Pure token-bucket arithmetic. No I/O and no clock of its own."""

    def __init__(self, spec: BucketSpec) -> None:
        self.spec = spec

    def replenish(self, tokens: float, last_ts: float, now: float) -> float:
        """Tokens available at ``now`` given the bucket was ``tokens`` at ``last_ts``."""
        if now <= last_ts:
            return min(self.spec.capacity, tokens)
        refilled = tokens + (now - last_ts) * self.spec.refill_per_sec
        return min(self.spec.capacity, refilled)

    def consume(
        self,
        tokens: float,
        last_ts: float,
        now: float,
        amount: float = 1.0,
        reserve: float = 0.0,
    ) -> Decision:
        """Try to take ``amount`` tokens; report the outcome and any wait.

        ``reserve`` is a cushion a low-priority caller must leave untouched: it
        is allowed only when ``available >= amount + reserve``, but consumes just
        ``amount``. Backfills pass a reserve so incremental syncs and interactive
        requests always find tokens.
        """
        available = self.replenish(tokens, last_ts, now)
        needed = amount + reserve
        if available >= needed:
            return Decision(True, available - amount, 0.0)
        deficit = needed - available
        retry = deficit / self.spec.refill_per_sec if self.spec.refill_per_sec > 0 else -1.0
        return Decision(False, available, retry)


def bucket_id(api_key: str | None) -> str:
    """A stable, non-secret Redis identifier for a key's bucket.

    The raw key never appears in a Redis key name — only a truncated SHA-256.
    """
    if not api_key:
        return "nvd:bucket:keyless"
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"nvd:bucket:{digest}"


# Atomic refill-then-consume (mirrors TokenBucket.consume, including the reserve).
# KEYS[1] = bucket hash key; ARGV = capacity, refill_per_sec, now, amount,
# ttl_seconds, reserve.
_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local amount = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local reserve = tonumber(ARGV[6] or "0")
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then tokens = capacity; ts = now end
if now > ts then
  tokens = math.min(capacity, tokens + (now - ts) * refill)
  ts = now
end
local allowed = 0
local retry = 0
if tokens >= amount + reserve then
  tokens = tokens - amount
  allowed = 1
else
  if refill > 0 then retry = (amount + reserve - tokens) / refill else retry = -1 end
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', ts)
redis.call('EXPIRE', key, ttl)
return {allowed, tostring(tokens), tostring(retry)}
"""


class RedisRateLimiter:
    """Blocks until a token is free in the per-key bucket held in Redis."""

    def __init__(
        self,
        redis_client,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], float] = time.time,
        max_wait: float = 120.0,
        poll_ceiling: float = 5.0,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis_client
        self._sleep = sleeper
        self._now = now_fn
        self._max_wait = max_wait
        self._poll_ceiling = poll_ceiling
        self._ttl = ttl_seconds
        self._script = redis_client.register_script(_LUA)

    def acquire(
        self, spec: BucketSpec, bucket: str, amount: float = 1.0, reserve: float = 0.0
    ) -> None:
        """Consume ``amount`` from ``bucket``, waiting (across workers) if needed.

        With a ``reserve``, wait until the bucket holds more than that cushion
        (see :meth:`TokenBucket.consume`)."""
        waited = 0.0
        while True:
            allowed, _tokens, retry = self._script(
                keys=[bucket],
                args=[spec.capacity, spec.refill_per_sec, self._now(), amount, self._ttl, reserve],
            )
            if int(allowed) == 1:
                return
            wait = float(retry)
            if wait < 0:
                raise RuntimeError("rate-limit bucket cannot refill (refill_per_sec=0)")
            # Re-check periodically rather than trusting one long sleep — another
            # worker may consume the token that frees up first.
            wait = min(wait, self._poll_ceiling)
            waited += wait
            if waited > self._max_wait:
                raise TimeoutError(f"timed out after {self._max_wait}s waiting for NVD token")
            self._sleep(wait)
