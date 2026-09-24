"""Sign in with Google (OIDC code flow + PKCE).

API tests run the whole browser round trip against the development stand-in,
which speaks the same protocol as Google (state cookie, nonce, PKCE, an RS256
ID token through the same verifier). The Google provider itself is tested
offline against a fake HTTP session serving discovery, JWKS and token responses.
"""
import base64
import hashlib
import hmac
import json
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.sso import get_oidc_provider, safe_next
from app.config import Settings, get_settings
from app.models import User, UserIdentity
from app.security import create_token
from app.services import sso_service
from app.services.oidc import (
    DevOidcProvider,
    GoogleOidcProvider,
    OidcError,
    OidcIdentity,
    build_provider,
    identity_from_claims,
    pkce_challenge,
    verify_id_token,
)

API = "/api/v1"
BASE = "http://testserver"


@pytest.fixture
def sso(api, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", BASE)
    get_settings.cache_clear()
    dev = DevOidcProvider(base_url=BASE)
    api.app.dependency_overrides[get_oidc_provider] = lambda: dev
    return dev


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _start(client, next_path=None):
    params = {"next": next_path} if next_path is not None else None
    res = client.get(f"{API}/auth/google/start", params=params, follow_redirects=False)
    assert res.status_code == 302, res.text
    return res


def _approve(client, authorize_url, email, *, verified=True, name="", action="approve"):
    q = _query(authorize_url)
    params = {k: q[k] for k in ("redirect_uri", "state", "nonce", "code_challenge")}
    params.update(action=action, email=email, name=name)
    if verified:
        params["email_verified"] = "on"
    return client.get(f"{API}/auth/dev-oidc/approve", params=params, follow_redirects=False)


def sign_in(client, email, *, verified=True, name="", next_path=None):
    """Start -> the stand-in's login page -> approve -> callback. Returns the
    callback response (a redirect into the app or back to /login)."""
    authorize_url = _start(client, next_path).headers["location"]
    assert client.get(authorize_url).status_code == 200  # the login page renders
    approved = _approve(client, authorize_url, email, verified=verified, name=name)
    assert approved.status_code == 302
    return client.get(approved.headers["location"], follow_redirects=False)


def _user(api, email):
    with api.db() as db:
        return db.query(User).filter_by(email=email).one_or_none()


# --------------------------------------------------------------------------- #
# Provider discovery                                                           #
# --------------------------------------------------------------------------- #
def test_nothing_is_exposed_when_google_is_not_configured(api):
    client = api.client()
    assert client.get(f"{API}/auth/providers").json() == []
    assert client.get(f"{API}/auth/google/start", follow_redirects=False).status_code == 404
    assert client.get(f"{API}/auth/google/callback?code=x&state=y").status_code == 404
    assert client.get(f"{API}/auth/dev-oidc/authorize").status_code == 404


def test_providers_flag_the_development_stand_in(api, sso):
    assert api.client().get(f"{API}/auth/providers").json() == [
        {"id": "google", "name": "Google", "dev_stand_in": True}
    ]


# --------------------------------------------------------------------------- #
# Account resolution through the full flow                                     #
# --------------------------------------------------------------------------- #
def test_first_google_sign_in_creates_an_account_and_org(api, sso):
    client = api.client()
    res = sign_in(client, "New.Person@Example.com", name="New Person")
    assert res.status_code == 302 and res.headers["location"] == "/"
    assert res.headers["cache-control"] == "no-store"

    me = client.get(f"{API}/auth/me").json()
    assert me["email"] == "new.person@example.com" and me["name"] == "New Person"
    orgs = client.get(f"{API}/orgs").json()
    assert len(orgs) == 1 and orgs[0]["role"] == "owner"
    # No password was ever set, so the password form can't be used.
    login = api.client().post(f"{API}/auth/login",
                              json={"email": "new.person@example.com", "password": "anything1"})
    assert login.status_code == 401
    with api.db() as db:
        link = db.query(UserIdentity).one()
        assert link.provider == "google" and link.email == "new.person@example.com"
        assert db.get(User, link.user_id).password_hash is None


def test_signing_in_again_reuses_the_same_account(api, sso):
    first, second = api.client(), api.client()
    sign_in(first, "repeat@example.com")
    sign_in(second, "repeat@example.com")
    assert first.get(f"{API}/auth/me").json()["id"] == second.get(f"{API}/auth/me").json()["id"]
    assert len(second.get(f"{API}/orgs").json()) == 1  # no second personal org
    with api.db() as db:
        assert db.query(UserIdentity).count() == 1


def test_links_to_an_existing_password_account_with_the_same_email(api, sso):
    owner, _ = api.register("owner@acme.io", org_name="Acme")
    uid = owner.get(f"{API}/auth/me").json()["id"]

    google = api.client()
    assert sign_in(google, "OWNER@acme.io").headers["location"] == "/"
    assert google.get(f"{API}/auth/me").json()["id"] == uid
    assert [o["name"] for o in google.get(f"{API}/orgs").json()] == ["Acme"]
    # The password keeps working alongside Google.
    login = api.client().post(f"{API}/auth/login",
                              json={"email": "owner@acme.io", "password": "password123"})
    assert login.status_code == 200


def test_unverified_email_is_refused_and_nothing_is_created(api, sso):
    client = api.client()
    res = sign_in(client, "shady@example.com", verified=False)
    assert res.headers["location"] == "/login?sso_error=unverified"
    assert _user(api, "shady@example.com") is None
    assert client.get(f"{API}/auth/me").status_code == 401


def test_unverified_email_cannot_take_over_an_existing_account(api, sso):
    api.register("victim@acme.io")
    res = sign_in(api.client(), "victim@acme.io", verified=False)
    assert res.headers["location"] == "/login?sso_error=unverified"
    with api.db() as db:
        assert db.query(UserIdentity).count() == 0


def test_inactive_account_is_refused(api, sso):
    api.register("gone@acme.io")
    with api.db() as db:
        db.query(User).filter_by(email="gone@acme.io").one().is_active = False
        db.commit()
    res = sign_in(api.client(), "gone@acme.io")
    assert res.headers["location"] == "/login?sso_error=disabled"


def test_a_second_google_account_cannot_attach_to_a_linked_user(api):
    api.register("dup@acme.io")
    first = OidcIdentity("google", "sub-A", "dup@acme.io", True, None)
    other = OidcIdentity("google", "sub-B", "dup@acme.io", True, None)
    with api.db() as db:
        user, outcome = sso_service.resolve_user(db, first)
        assert outcome == "linked"
        assert sso_service.resolve_user(db, first) == (user, "signed_in")
        with pytest.raises(OidcError) as err:
            sso_service.resolve_user(db, other)
        assert err.value.code == "conflict"


def test_identity_is_matched_by_subject_not_email(api):
    """If the Google account's email changes, the link (by sub) still holds."""
    with api.db() as db:
        user, outcome = sso_service.resolve_user(
            db, OidcIdentity("google", "sub-1", "old@example.com", True, "Pat")
        )
        assert outcome == "created"
        again, outcome = sso_service.resolve_user(
            db, OidcIdentity("google", "sub-1", "new@example.com", True, "Pat")
        )
        assert (again.id, outcome) == (user.id, "signed_in")
        assert db.query(UserIdentity).one().email == "new@example.com"


# --------------------------------------------------------------------------- #
# Flow integrity                                                               #
# --------------------------------------------------------------------------- #
def test_cancelling_at_the_provider(api, sso):
    client = api.client()
    authorize_url = _start(client).headers["location"]
    cancelled = _approve(client, authorize_url, "", action="cancel")
    res = client.get(cancelled.headers["location"], follow_redirects=False)
    assert res.headers["location"] == "/login?sso_error=cancelled"


def test_tampered_state_is_rejected(api, sso):
    client = api.client()
    authorize_url = _start(client).headers["location"]
    callback = _approve(client, authorize_url, "csrf@example.com").headers["location"]
    q = _query(callback)
    res = client.get(f"{API}/auth/google/callback",
                     params={"code": q["code"], "state": "attacker-state"},
                     follow_redirects=False)
    assert res.headers["location"] == "/login?sso_error=expired"
    assert _user(api, "csrf@example.com") is None


def test_callback_without_this_browsers_flow_cookie_is_rejected(api, sso):
    """Login CSRF: a callback URL planted in another browser has no flow cookie."""
    attacker = api.client()
    authorize_url = _start(attacker).headers["location"]
    callback = _approve(attacker, authorize_url, "attacker@example.com").headers["location"]
    victim = api.client()
    res = victim.get(callback, follow_redirects=False)
    assert res.headers["location"] == "/login?sso_error=expired"
    assert victim.get(f"{API}/auth/me").status_code == 401


def test_callback_cannot_be_replayed(api, sso):
    client = api.client()
    authorize_url = _start(client).headers["location"]
    callback = _approve(client, authorize_url, "once@example.com").headers["location"]
    assert client.get(callback, follow_redirects=False).headers["location"] == "/"
    # The flow cookie was cleared on success, so the same URL is dead.
    assert client.get(callback, follow_redirects=False).headers["location"] == (
        "/login?sso_error=expired"
    )


def test_code_from_another_flow_fails_pkce(api, sso):
    client = api.client()
    other = _start(api.client()).headers["location"]  # someone else's flow
    stolen = _query(_approve(api.client(), other, "pkce@example.com").headers["location"])
    mine = _query(_start(client).headers["location"])
    res = client.get(f"{API}/auth/google/callback",
                     params={"code": stolen["code"], "state": mine["state"]},
                     follow_redirects=False)
    assert res.headers["location"] == "/login?sso_error=failed"
    assert _user(api, "pkce@example.com") is None


def test_flow_cookie_is_httponly_lax_scoped_and_short_lived(api, sso):
    res = _start(api.client())
    cookie = SimpleCookie(res.headers["set-cookie"])["oidc_flow"]
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/api/v1/auth/"
    assert cookie["max-age"] == "600"


@pytest.mark.parametrize(
    ("requested", "landing"),
    [
        ("/vendors?tier=High", "/vendors?tier=High"),
        ("/reports", "/reports"),
        ("//evil.example", "/"),
        ("https://evil.example/", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("", "/"),
    ],
)
def test_return_path_is_same_site_only(api, sso, requested, landing):
    res = sign_in(api.client(), "next@example.com", next_path=requested)
    assert res.headers["location"] == landing


def test_start_hops_to_the_configured_host_first(api, sso, monkeypatch):
    """Opened at another host (127.0.0.1 vs localhost): the flow cookie would
    land on the wrong host, so start re-runs on APP_BASE_URL's host."""
    monkeypatch.setenv("APP_BASE_URL", "http://app.example:8080")
    get_settings.cache_clear()
    res = api.client().get(f"{API}/auth/google/start", params={"next": "//evil.example"},
                           follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == (
        "http://app.example:8080/api/v1/auth/google/start?next=%2F"
    )
    assert "set-cookie" not in res.headers  # no flow started on the wrong host


def test_safe_next_rejects_control_characters():
    assert safe_next("/ok") == "/ok"
    assert safe_next("/a\r\nSet-Cookie:x") == "/"
    assert safe_next("/" + "a" * 600) == "/"
    assert safe_next(None) == "/"


def test_stand_in_only_redirects_to_our_callback(api, sso):
    client = api.client()
    q = _query(_start(client).headers["location"])
    q["redirect_uri"] = "https://evil.example/cb"
    assert client.get(f"{API}/auth/dev-oidc/authorize", params=q).status_code == 400
    params = {k: q[k] for k in ("redirect_uri", "state", "nonce", "code_challenge")}
    res = client.get(f"{API}/auth/dev-oidc/approve",
                     params={**params, "email": "x@example.com"}, follow_redirects=False)
    assert res.status_code == 400


def test_stand_in_page_escapes_input_and_sets_a_strict_csp(api, sso):
    client = api.client()
    q = _query(_start(client).headers["location"])
    q["state"] = '"><script>alert(1)</script>'
    page = client.get(f"{API}/auth/dev-oidc/authorize", params=q)
    assert page.status_code == 200
    assert "<script>alert(1)" not in page.text
    assert "&quot;&gt;&lt;script&gt;" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "Development stand-in" in page.text


def test_stand_in_rejects_an_invalid_email(api, sso):
    client = api.client()
    authorize_url = _start(client).headers["location"]
    res = _approve(client, authorize_url, "not-an-email")
    assert res.status_code == 422
    assert "valid email" in res.text


# --------------------------------------------------------------------------- #
# Token verification (shared by Google and the stand-in)                       #
# --------------------------------------------------------------------------- #
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ISS = "https://accounts.google.com"
_AUD = "client-123.apps.googleusercontent.com"


def _id_token(key=_KEY, *, kid="k1", alg="RS256", **overrides):
    now = int(time.time())
    claims = {
        "iss": _ISS, "aud": _AUD, "sub": "1234567890", "email": "Pat@Example.com",
        "email_verified": True, "name": "Pat Example", "nonce": "n-1",
        "iat": now, "exp": now + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _verify(token, nonce="n-1"):
    return verify_id_token(token, key=_KEY.public_key(), issuers=GoogleOidcProvider.ISSUERS,
                           audience=_AUD, nonce=nonce)


def test_pkce_matches_the_rfc_7636_example():
    assert pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_a_valid_id_token_verifies():
    assert _verify(_id_token())["sub"] == "1234567890"
    assert _verify(_id_token(iss="accounts.google.com"))["sub"]  # Google's legacy issuer


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"aud": "someone-else"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 3600},
        {"nonce": "n-other"},
        {"nonce": None},
        {"sub": None},
        {"azp": "someone-else"},
    ],
)
def test_bad_id_tokens_are_rejected(token_kwargs):
    with pytest.raises(OidcError) as err:
        _verify(_id_token(**token_kwargs))
    assert err.value.code == "invalid_token"


def test_other_signing_keys_and_algorithms_are_rejected():
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OidcError):
        _verify(_id_token(key=stranger))
    now = int(time.time())
    claims = {"iss": _ISS, "aud": _AUD, "sub": "x", "nonce": "n-1", "iat": now, "exp": now + 60}
    # Algorithm confusion: HMAC-signed with the *public* key as the secret.
    pem = _KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = (b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + "."
                     + b64(json.dumps(claims).encode()))
    forged = signing_input + "." + b64(hmac.new(pem, signing_input.encode(), hashlib.sha256).digest())
    with pytest.raises(OidcError):
        _verify(forged)
    # Unsigned ("alg": "none").
    with pytest.raises(OidcError):
        _verify(jwt.encode(claims, None, algorithm="none"))


def test_claims_become_a_normalized_identity():
    ident = identity_from_claims("google", {"sub": 42, "email": " Pat@Example.COM ",
                                            "email_verified": "true", "name": "x" * 300})
    assert ident == OidcIdentity("google", "42", "pat@example.com", True, "x" * 200)
    assert identity_from_claims("google", {"sub": "1", "email": "a@b.c"}).email_verified is False
    with pytest.raises(OidcError) as err:
        identity_from_claims("google", {"sub": "1"})
    assert err.value.code == "no_email"


def test_stand_in_checks_redirect_uri_pkce_and_expiry():
    dev = DevOidcProvider(base_url=BASE)
    cb = f"{BASE}/api/v1/auth/google/callback"
    verifier = "v" * 64
    code = dev.issue_code(email="a@example.com", name=None, email_verified=True,
                          redirect_uri=cb, nonce="n", code_challenge=pkce_challenge(verifier))
    assert dev.fetch_identity(code=code, code_verifier=verifier, redirect_uri=cb,
                              nonce="n").email == "a@example.com"
    for kwargs, reason in [
        ({"code_verifier": "w" * 64}, "exchange_failed"),
        ({"redirect_uri": f"{BASE}/elsewhere"}, "exchange_failed"),
        ({"nonce": "other"}, "invalid_token"),
    ]:
        args = {"code": code, "code_verifier": verifier, "redirect_uri": cb, "nonce": "n", **kwargs}
        with pytest.raises(OidcError) as err:
            dev.fetch_identity(**args)
        assert err.value.code == reason
    expired = create_token({"type": "dev_oidc_code", "email": "a@example.com"}, -10)
    with pytest.raises(OidcError):
        dev.fetch_identity(code=expired, code_verifier=verifier, redirect_uri=cb, nonce="n")


# --------------------------------------------------------------------------- #
# Google provider against a fake HTTP session                                  #
# --------------------------------------------------------------------------- #
DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
META = {
    "issuer": _ISS,
    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_endpoint": "https://oauth2.googleapis.com/token",
    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
}


def _jwk(key, kid):
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**data, "kid": kid, "alg": "RS256", "use": "sig"}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeGoogle:
    """Serves discovery, JWKS and the token endpoint; records every call."""

    def __init__(self):
        self.keys = {"k1": _KEY}
        self.token_response = FakeResponse(200, {"id_token": _id_token()})
        self.calls = []
        self.fail = False

    def get(self, url, timeout=None):
        self.calls.append(("GET", url))
        if self.fail:
            raise requests.ConnectionError("network down")
        if url == DISCOVERY:
            return FakeResponse(200, META)
        if url == META["jwks_uri"]:
            return FakeResponse(200, {"keys": [_jwk(k, kid) for kid, k in self.keys.items()]})
        raise AssertionError(url)

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, data))
        if self.fail:
            raise requests.ConnectionError("network down")
        assert url == META["token_endpoint"]
        return self.token_response


def _google(fake):
    return GoogleOidcProvider(client_id=_AUD, client_secret="shh", discovery_url=DISCOVERY,
                              session=fake)


def _fetch(provider):
    return provider.fetch_identity(code="auth-code", code_verifier="ver",
                                   redirect_uri="http://localhost:8080/cb", nonce="n-1")


def test_google_authorization_url_carries_the_flow_parameters():
    url = _google(FakeGoogle()).authorization_url(
        redirect_uri="http://localhost:8080/api/v1/auth/google/callback",
        state="st", nonce="no", code_challenge="ch",
    )
    assert url.startswith(META["authorization_endpoint"] + "?")
    q = _query(url)
    assert q == {
        "client_id": _AUD, "redirect_uri": "http://localhost:8080/api/v1/auth/google/callback",
        "response_type": "code", "scope": "openid email profile", "state": "st", "nonce": "no",
        "code_challenge": "ch", "code_challenge_method": "S256", "prompt": "select_account",
    }


def test_google_exchanges_the_code_and_verifies_the_token():
    fake = FakeGoogle()
    ident = _fetch(_google(fake))
    assert ident == OidcIdentity("google", "1234567890", "pat@example.com", True, "Pat Example")
    post = next(c for c in fake.calls if c[0] == "POST")
    assert post[2] == {
        "grant_type": "authorization_code", "code": "auth-code",
        "redirect_uri": "http://localhost:8080/cb", "client_id": _AUD,
        "client_secret": "shh", "code_verifier": "ver",
    }


def test_google_caches_discovery_and_keys():
    fake = FakeGoogle()
    provider = _google(fake)
    _fetch(provider)
    _fetch(provider)
    gets = [c[1] for c in fake.calls if c[0] == "GET"]
    assert gets == [DISCOVERY, META["jwks_uri"]]


def test_google_picks_up_rotated_keys_once():
    fake = FakeGoogle()
    provider = _google(fake)
    _fetch(provider)
    rotated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    fake.keys["k2"] = rotated
    fake.token_response = FakeResponse(200, {"id_token": _id_token(rotated, kid="k2")})
    assert _fetch(provider).subject == "1234567890"
    assert [c[1] for c in fake.calls if c[0] == "GET"].count(META["jwks_uri"]) == 2

    fake.token_response = FakeResponse(200, {"id_token": _id_token(rotated, kid="k9")})
    with pytest.raises(OidcError) as err:
        _fetch(provider)
    assert err.value.code == "invalid_token"


def test_google_token_endpoint_errors_are_not_shown_to_users():
    fake = FakeGoogle()
    fake.token_response = FakeResponse(400, {"error": "invalid_grant"})
    with pytest.raises(OidcError) as err:
        _fetch(_google(fake))
    assert err.value.code == "exchange_failed"
    fake.token_response = FakeResponse(200, {"access_token": "only"})
    with pytest.raises(OidcError) as err:
        _fetch(_google(fake))
    assert err.value.code == "exchange_failed"


def test_google_outage_is_reported_as_unavailable():
    fake = FakeGoogle()
    fake.fail = True
    with pytest.raises(OidcError) as err:
        _google(fake).authorization_url(redirect_uri="r", state="s", nonce="n", code_challenge="c")
    assert err.value.code == "unavailable"


def test_google_outage_at_start_lands_on_the_sign_in_page(api, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", BASE)
    get_settings.cache_clear()
    fake = FakeGoogle()
    fake.fail = True
    api.app.dependency_overrides[get_oidc_provider] = lambda: _google(fake)
    res = api.client().get(f"{API}/auth/google/start", follow_redirects=False)
    assert res.headers["location"] == "/login?sso_error=unavailable"


# --------------------------------------------------------------------------- #
# Provider selection                                                           #
# --------------------------------------------------------------------------- #
def test_provider_selection():
    assert build_provider(Settings(google_client_id=None, google_client_secret=None,
                                   oidc_dev_provider=False)) is None
    real = build_provider(Settings(google_client_id="id", google_client_secret="secret",
                                   oidc_dev_provider=True))
    assert isinstance(real, GoogleOidcProvider)  # real credentials always win
    dev = build_provider(Settings(google_client_id=None, google_client_secret=None,
                                  oidc_dev_provider=True))
    assert isinstance(dev, DevOidcProvider)
    # Half-configured Google falls back to the stand-in only if that's enabled.
    assert build_provider(Settings(google_client_id="id", google_client_secret=None,
                                   oidc_dev_provider=False)) is None
    # Never in production.
    assert build_provider(Settings(env="production", google_client_id=None,
                                   google_client_secret=None, oidc_dev_provider=True)) is None
