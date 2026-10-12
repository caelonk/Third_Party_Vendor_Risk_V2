"""A real NVD API key: confirmed with NVD when it is saved, and a key NVD refuses
is reported as exactly that (not as a generic fetch failure).

NVD answers a bad key with ``404`` and a ``message: Invalid apiKey.`` header;
these tests replay that response. No test talks to NVD.
"""
import pytest
import requests

from app.api.integrations import get_nvd_key_checker
from app.services import integration_service
from core import nvd_client

API = "/api/v1"


class FakeResponse:
    def __init__(self, status_code=200, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {"totalResults": 1, "vulnerabilities": []}

    def json(self):
        return self._payload


class FakeSession:
    """Returns the queued responses in order; records what was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


INVALID = FakeResponse(404, {"message": "Invalid apiKey."})


# --------------------------------------------------------------------------- #
# The client                                                                   #
# --------------------------------------------------------------------------- #
def test_the_key_is_sent_in_the_apikey_header():
    session = nvd_client.make_session(nvd_client.NVDConfig(api_key="my-key"))
    assert session.headers["apiKey"] == "my-key"
    assert "apiKey" not in nvd_client.make_session(nvd_client.NVDConfig()).headers


def test_a_key_raises_the_pacing_to_the_keyed_rate():
    assert nvd_client.NVDConfig(api_key="k").pacing == nvd_client.PACE_WITH_KEY
    assert nvd_client.NVDConfig().pacing == nvd_client.PACE_KEYLESS


def test_check_reports_a_valid_key_with_one_small_request():
    session = FakeSession(FakeResponse(200))
    assert nvd_client.check_api_key("good", session=session) == "valid"
    assert session.calls == [(nvd_client.BASE_URL, {"cveId": nvd_client.KEY_CHECK_CVE})]


def test_check_reports_a_key_nvd_refuses():
    assert nvd_client.check_api_key("bad", session=FakeSession(INVALID)) == "invalid"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(403),                       # rate limited
        FakeResponse(503),                       # NVD down
        FakeResponse(404),                       # a 404 without NVD's message is not a verdict
        requests.ConnectionError("no route"),    # unreachable
        requests.Timeout("slow"),
    ],
)
def test_check_gives_no_verdict_when_nvd_cannot_answer(response):
    assert nvd_client.check_api_key("maybe", session=FakeSession(response)) == "unknown"


def test_a_refused_key_fails_a_fetch_at_once_with_a_clear_message():
    session = FakeSession(INVALID)
    slept = []
    with pytest.raises(nvd_client.InvalidApiKeyError, match="rejected the API key"):
        nvd_client.fetch_query(
            "cpe:2.3:a:apache:log4j", "recent", session=session,
            config=nvd_client.NVDConfig(api_key="revoked"), log=lambda *_: None,
            sleeper=slept.append,
        )
    assert len(session.calls) == 1       # not retried: retrying cannot help
    assert slept == [nvd_client.PACE_WITH_KEY]  # only the normal pacing, no backoff


def test_rate_limiting_is_still_retried():
    session = FakeSession(FakeResponse(403), FakeResponse(200))
    payload = nvd_client.fetch_query(
        "cpe:2.3:a:apache:log4j", "kev", session=session,
        config=nvd_client.NVDConfig(api_key="k"), log=lambda *_: None, sleeper=lambda _s: None,
    )
    assert len(session.calls) == 2 and payload["vulnerabilities"] == []


# --------------------------------------------------------------------------- #
# Saving a key in Settings                                                     #
# --------------------------------------------------------------------------- #
def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def _checker(api, verdict):
    seen = []

    def check(key):
        seen.append(key)
        return verdict

    api.app.dependency_overrides[get_nvd_key_checker] = lambda: check
    return seen


def test_a_key_nvd_accepts_is_saved_as_verified(api):
    client, _ = api.register("key1@acme.io")
    oid = _org_id(client)
    seen = _checker(api, "valid")
    body = client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "  real-key  "}).json()
    assert seen == ["real-key"]  # checked once, trimmed
    assert body["nvd_key_set"] is True and body["nvd_key_verified_at"] is not None
    with api.db() as db:
        assert integration_service.resolve_nvd_api_key(db, oid) == "real-key"


def test_a_key_nvd_refuses_is_not_saved(api):
    client, _ = api.register("key2@acme.io")
    oid = _org_id(client)
    api.set_plan(oid, "team")
    _checker(api, "valid")
    client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "working-key"})

    _checker(api, "invalid")
    res = client.put(
        f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "typo-key", "sync_cadence_hours": 6}
    )
    assert res.status_code == 422 and "did not accept" in res.json()["detail"]
    # Nothing from the refused request was applied: the old key and cadence stand.
    body = client.get(f"{API}/orgs/{oid}/integration").json()
    assert body["nvd_key_set"] is True and body["sync_cadence_hours"] == 24
    with api.db() as db:
        assert integration_service.resolve_nvd_api_key(db, oid) == "working-key"


def test_a_key_is_saved_unverified_when_nvd_cannot_be_reached(api):
    client, _ = api.register("key3@acme.io")
    oid = _org_id(client)
    _checker(api, "unknown")
    body = client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "untested"}).json()
    assert body["nvd_key_set"] is True and body["nvd_key_verified_at"] is None


def test_removing_a_key_asks_nvd_nothing_and_clears_the_verification(api):
    client, _ = api.register("key4@acme.io")
    oid = _org_id(client)
    _checker(api, "valid")
    client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "k"})
    seen = _checker(api, "invalid")
    body = client.put(f"{API}/orgs/{oid}/integration", json={"nvd_api_key": ""}).json()
    assert seen == []
    assert body["nvd_key_set"] is False and body["nvd_key_verified_at"] is None


def test_changing_only_the_schedule_does_not_recheck_the_key(api):
    client, _ = api.register("key5@acme.io")
    oid = _org_id(client)
    _checker(api, "valid")
    verified = client.put(
        f"{API}/orgs/{oid}/integration", json={"nvd_api_key": "k"}
    ).json()["nvd_key_verified_at"]
    seen = _checker(api, "invalid")
    body = client.put(f"{API}/orgs/{oid}/integration", json={"sync_cadence_hours": 48}).json()
    assert seen == [] and body["nvd_key_verified_at"] == verified
