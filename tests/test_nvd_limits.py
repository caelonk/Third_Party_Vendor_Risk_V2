"""The shared NVD throttle: priorities (backfill reserve), wait caps, graceful
degradation without Redis, and that every NVD caller goes through it."""
import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.services import cpe_service, nvd_limits, sync_service
from app.services.exceptions import UnavailableError
from core import nvd_client


class FakeRedis:
    """Stands in for redis-py: records Lua calls and replays scripted results."""

    def __init__(self, results=None, error=None):
        self.calls = []
        self._results = list(results or [(1, "0", "0")])
        self._error = error

    def register_script(self, _lua):
        def script(keys, args):
            self.calls.append({"keys": keys, "args": args})
            if self._error:
                raise self._error
            return self._results.pop(0) if len(self._results) > 1 else self._results[0]

        return script


@pytest.fixture(autouse=True)
def _fresh_warning_flag(monkeypatch):
    monkeypatch.setattr(nvd_limits, "_warned_degraded", False)


def test_spec_matches_nvd_windows():
    assert nvd_limits.spec_for("key").capacity == 50
    assert nvd_limits.spec_for(None).capacity == 5


def test_backfill_draws_with_a_reserve_interactive_does_not():
    r = FakeRedis()
    nvd_limits.NvdThrottle(None, backfill=True, redis_client=r).wait()
    nvd_limits.NvdThrottle(None, redis_client=r).wait()
    reserves = [call["args"][5] for call in r.calls]
    assert reserves == [2.0, 0.0]  # ceil(5 * 0.3) = 2 for a keyless backfill
    nvd_limits.NvdThrottle("k", backfill=True, redis_client=r).wait()
    assert r.calls[-1]["args"][5] == 15.0  # ceil(50 * 0.3)


def test_buckets_are_per_key_and_never_contain_the_key():
    r = FakeRedis()
    nvd_limits.NvdThrottle("org-secret-key", redis_client=r).wait()
    bucket = r.calls[0]["keys"][0]
    assert bucket.startswith("nvd:bucket:") and "org-secret-key" not in bucket


def test_starved_bucket_raises_rate_limit_busy():
    # Always denied with a 10s retry; a 1s cap gives up without sleeping.
    r = FakeRedis(results=[(0, "0", "10")])
    with pytest.raises(nvd_limits.RateLimitBusy):
        nvd_limits.NvdThrottle(None, max_wait=1, redis_client=r).wait()


def test_redis_down_degrades_to_local_pacing_and_warns_once(caplog):
    r = FakeRedis(error=RedisConnectionError("refused"))
    with caplog.at_level(logging.WARNING, logger="app.services.nvd_limits"):
        t = nvd_limits.NvdThrottle(None, redis_client=r)
        t.wait()
        t.wait()  # no second Redis attempt once degraded
        nvd_limits.NvdThrottle(None, redis_client=r).wait()
    assert len(r.calls) == 2  # one per throttle instance, then degraded
    assert sum("falling back to per-process pacing" in m for m in caplog.messages) == 1


# --------------------------------------------------------------------------- #
# Interactive callers go through the throttle                                 #
# --------------------------------------------------------------------------- #
class RecordingThrottle:
    instances: list = []

    def __init__(self, api_key, **kw):
        self.api_key, self.kw, self.waits = api_key, kw, 0
        RecordingThrottle.instances.append(self)

    def wait(self):
        self.waits += 1


class BusyThrottle(RecordingThrottle):
    def wait(self):
        raise nvd_limits.RateLimitBusy("starved")


def test_sync_button_fetch_waits_on_the_shared_bucket(monkeypatch):
    RecordingThrottle.instances = []
    monkeypatch.setattr(nvd_client, "fetch_query", lambda *a, **k: {"vulnerabilities": []})
    fetch = sync_service.build_live_fetch(api_key="org-key", throttle_factory=RecordingThrottle)
    fetch({"cpe_prefix": "cpe:2.3:a:x:y"}, "recent")
    fetch({"cpe_prefix": "cpe:2.3:a:x:y"}, "kev")
    t = RecordingThrottle.instances[0]
    assert t.api_key == "org-key" and t.waits == 2
    assert t.kw["max_wait"] == 20.0  # interactive cap, not the 120s worker cap


def test_sync_button_turns_a_starved_bucket_into_a_fetch_error(monkeypatch):
    monkeypatch.setattr(nvd_client, "fetch_query", lambda *a, **k: pytest.fail("must not call NVD"))
    fetch = sync_service.build_live_fetch(api_key=None, throttle_factory=BusyThrottle)
    with pytest.raises(nvd_client.VendorFetchError, match="rate limit busy"):
        fetch({"cpe_prefix": "cpe:2.3:a:x:y"}, "recent")


def test_sync_button_uses_the_orgs_own_key(api, monkeypatch):
    from app.services import integration_service

    client, _ = api.register("key@acme.io")
    oid = client.get("/api/v1/orgs").json()[0]["id"]
    seen = {}
    monkeypatch.setattr(
        nvd_client, "fetch_query",
        lambda prefix, qt, *, config, **k: seen.setdefault("key", config.api_key) and {"vulnerabilities": []},
    )
    with api.db() as db:
        integration_service.update_integration(db, oid, nvd_api_key="org-own-key")
        sync_service.live_fetch_for_org(db, oid)({"cpe_prefix": "cpe:2.3:a:x:y"}, "recent")
    assert seen["key"] == "org-own-key"


def test_cpe_search_busy_or_down_is_a_503_not_a_500(api, monkeypatch):
    client, _ = api.register("cpe503@acme.io")
    oid = client.get("/api/v1/orgs").json()[0]["id"]
    with api.db() as db:
        busy = cpe_service.build_live_cpe_fetch(db, oid, throttle_factory=BusyThrottle)
        with pytest.raises(UnavailableError, match="busy"):
            busy("fortios")

        def boom(*a, **k):
            raise nvd_client.VendorFetchError("HTTP 503")

        monkeypatch.setattr(nvd_client, "search_cpes", boom)
        down = cpe_service.build_live_cpe_fetch(db, oid, throttle_factory=RecordingThrottle)
        with pytest.raises(UnavailableError, match="unavailable"):
            down("fortios")

    # And through the API it is an actionable 503.
    from app.api import cpe as cpe_api

    def unavailable(_kw):
        raise UnavailableError("NVD is busy right now (rate limit). Try again in a moment.")

    api.app.dependency_overrides[cpe_api.get_cpe_fetcher] = lambda: unavailable
    res = client.get(f"/api/v1/orgs/{oid}/cpe-search", params={"q": "fortios"})
    assert res.status_code == 503 and "Try again" in res.json()["detail"]
