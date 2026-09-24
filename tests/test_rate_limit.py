"""Pure token-bucket arithmetic (the Redis layer is verified live in Docker)."""
import pytest

from app.workers.rate_limit import BucketSpec, TokenBucket, bucket_id


def test_from_window_derives_capacity_and_rate():
    spec = BucketSpec.from_window(50, 30)
    assert spec.capacity == 50
    assert spec.refill_per_sec == 50 / 30


def test_fresh_bucket_allows_up_to_capacity():
    bucket = TokenBucket(BucketSpec(capacity=3, refill_per_sec=1))
    d = bucket.consume(tokens=3, last_ts=0.0, now=0.0)
    assert d.allowed and d.tokens == 2 and d.retry_after == 0.0


def test_empty_bucket_denies_and_reports_wait():
    bucket = TokenBucket(BucketSpec(capacity=5, refill_per_sec=2))  # 2 tokens/sec
    d = bucket.consume(tokens=0.0, last_ts=10.0, now=10.0)
    assert not d.allowed
    assert d.retry_after == 0.5  # need 1 token at 2/sec


def test_replenish_accrues_over_time_and_caps_at_capacity():
    bucket = TokenBucket(BucketSpec(capacity=5, refill_per_sec=1))
    # 3 seconds at 1/sec from empty -> 3 tokens.
    assert bucket.replenish(tokens=0.0, last_ts=0.0, now=3.0) == 3.0
    # 100 seconds cannot exceed capacity.
    assert bucket.replenish(tokens=0.0, last_ts=0.0, now=100.0) == 5.0


def test_consume_after_partial_refill():
    bucket = TokenBucket(BucketSpec(capacity=10, refill_per_sec=1))
    # empty at t=0; at t=2 there are 2 tokens, consume 1 -> 1 left.
    d = bucket.consume(tokens=0.0, last_ts=0.0, now=2.0, amount=1.0)
    assert d.allowed and d.tokens == 1.0


def test_clock_going_backwards_never_adds_tokens():
    bucket = TokenBucket(BucketSpec(capacity=5, refill_per_sec=1))
    assert bucket.replenish(tokens=2.0, last_ts=10.0, now=5.0) == 2.0


def test_zero_refill_reports_unsatisfiable():
    bucket = TokenBucket(BucketSpec(capacity=1, refill_per_sec=0))
    d = bucket.consume(tokens=0.0, last_ts=0.0, now=0.0)
    assert not d.allowed and d.retry_after == -1.0


def test_reserve_holds_back_a_cushion_for_higher_priority_callers():
    # capacity 10, refill 1/s; a backfill must leave 3 tokens in the bucket.
    bucket = TokenBucket(BucketSpec(capacity=10, refill_per_sec=1))
    assert bucket.consume(tokens=4.0, last_ts=0.0, now=0.0, reserve=3).allowed  # 4 >= 1+3
    denied = bucket.consume(tokens=3.5, last_ts=0.0, now=0.0, reserve=3)
    assert not denied.allowed
    assert denied.retry_after == pytest.approx(0.5)  # needs 4.0, has 3.5, at 1/s
    # The same 3.5 tokens are available to a caller without a reserve.
    assert bucket.consume(tokens=3.5, last_ts=0.0, now=0.0).allowed


def test_reserve_only_withholds_it_never_consumes_it():
    bucket = TokenBucket(BucketSpec(capacity=10, refill_per_sec=1))
    d = bucket.consume(tokens=10.0, last_ts=0.0, now=0.0, reserve=3)
    assert d.allowed and d.tokens == 9.0  # took 1, not 1 + 3


def test_bucket_id_is_stable_and_hides_the_key():
    assert bucket_id(None) == "nvd:bucket:keyless"
    one = bucket_id("super-secret-key")
    assert one == bucket_id("super-secret-key")     # stable
    assert "super-secret-key" not in one            # never leaks the raw key
    assert one != bucket_id("another-key")          # distinct per key
