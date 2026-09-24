"""OpenID Connect sign-in: the provider port, Google, and a development stand-in.

The flow is the authorization-code flow with PKCE (S256), a ``state`` value bound
to the browser (login CSRF), and a ``nonce`` bound to the ID token (replay). The
ID token's signature, issuer, audience, expiry and nonce are all checked before
any account is touched — see :func:`verify_id_token`.

* :class:`GoogleOidcProvider` — accounts.google.com via its discovery document.
  Signing keys come from Google's JWKS, cached, and re-fetched on an unknown
  ``kid`` (key rotation).
* :class:`DevOidcProvider` — a built-in stand-in for development and tests. It
  speaks the same protocol (state, nonce, PKCE, an RS256 ID token checked by the
  same verifier), but its login page is a form that accepts any email. It is
  never enabled in production, nor when real Google credentials are set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa

from ..config import Settings, get_settings
from ..security import create_token, decode_token

log = logging.getLogger(__name__)

CALLBACK_PATH = "/api/v1/auth/google/callback"
DEV_AUTHORIZE_PATH = "/api/v1/auth/dev-oidc/authorize"
SCOPES = "openid email profile"
_HTTP_TIMEOUT = 10
_CACHE_SECONDS = 3600
_LEEWAY_SECONDS = 60  # clock skew tolerated on exp/iat
_MAX_NAME = 200  # users.name


class OidcError(Exception):
    """Sign-in failed. ``code`` is a stable, user-safe reason the UI maps to a
    message; the exception text is for the logs only."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class OidcIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    name: str | None


# --------------------------------------------------------------------------- #
# Protocol pieces shared by every provider                                     #
# --------------------------------------------------------------------------- #
def new_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)  # 86 chars; RFC 7636 allows 43-128


def pkce_challenge(verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _same(a: object, b: str) -> bool:
    return hmac.compare_digest(str(a or "").encode(), b.encode())


def verify_id_token(
    id_token: str, *, key: Any, issuers: tuple[str, ...], audience: str, nonce: str
) -> dict[str, Any]:
    """Check an ID token completely, or raise ``OidcError("invalid_token")``.

    RS256 only (no "none", no HMAC confusion with a public key), required
    claims present, audience is us, issuer is the provider, not expired, and
    the nonce is the one this browser's flow generated.
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=audience,
            leeway=_LEEWAY_SECONDS,
            options={"require": ["iss", "sub", "aud", "exp", "iat"]},
        )
    except jwt.InvalidTokenError as exc:
        raise OidcError("invalid_token", f"ID token rejected: {exc}") from exc
    if claims.get("iss") not in issuers:
        raise OidcError("invalid_token", f"unexpected issuer {claims.get('iss')!r}")
    # With several audiences, the authorized party must be this client.
    if claims.get("azp") is not None and claims["azp"] != audience:
        raise OidcError("invalid_token", "azp does not match the client id")
    if not _same(claims.get("nonce"), nonce):
        raise OidcError("invalid_token", "nonce mismatch")
    return claims


def identity_from_claims(provider: str, claims: dict[str, Any]) -> OidcIdentity:
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise OidcError("no_email", "ID token carries no email")
    verified = claims.get("email_verified")
    if isinstance(verified, str):  # some providers send "true"/"false"
        verified = verified.lower() == "true"
    name = claims.get("name")
    name = name.strip()[:_MAX_NAME] if isinstance(name, str) else ""
    return OidcIdentity(
        provider=provider,
        subject=str(claims["sub"]),
        email=email.strip().lower(),
        email_verified=verified is True,
        name=name or None,
    )


class OidcProvider(Protocol):
    id: str
    dev_stand_in: bool

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> OidcIdentity: ...


# --------------------------------------------------------------------------- #
# Google                                                                       #
# --------------------------------------------------------------------------- #
class GoogleOidcProvider:
    id = "google"
    dev_stand_in = False
    ISSUERS = ("https://accounts.google.com", "accounts.google.com")

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        discovery_url: str,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self._discovery_url = discovery_url
        self._http = session or requests.Session()
        self._clock = clock
        self._lock = threading.Lock()
        self._meta: dict[str, Any] | None = None
        self._meta_at = 0.0
        self._keys: dict[str, Any] = {}  # kid -> public key
        self._keys_at = 0.0

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            resp = self._http.get(url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise OidcError("unavailable", f"GET {url} failed: {exc}") from exc
        if not isinstance(data, dict):
            raise OidcError("unavailable", f"GET {url}: expected a JSON object")
        return data

    def _metadata(self) -> dict[str, Any]:
        with self._lock:
            if self._meta is None or self._clock() - self._meta_at > _CACHE_SECONDS:
                self._meta = self._get_json(self._discovery_url)
                self._meta_at = self._clock()
            return self._meta

    def _load_keys(self) -> None:
        data = self._get_json(self._metadata()["jwks_uri"])
        try:
            keyset = jwt.PyJWKSet.from_dict(data)
        except jwt.PyJWKSetError as exc:
            raise OidcError("unavailable", f"unusable JWKS: {exc}") from exc
        with self._lock:
            self._keys = {k.key_id: k.key for k in keyset.keys if k.key_id}
            self._keys_at = self._clock()

    def _signing_key(self, id_token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except jwt.InvalidTokenError as exc:
            raise OidcError("invalid_token", f"malformed ID token: {exc}") from exc
        if not isinstance(kid, str):
            raise OidcError("invalid_token", "ID token header has no key id")
        stale = self._clock() - self._keys_at > _CACHE_SECONDS
        if stale or kid not in self._keys:
            self._load_keys()  # once per token: picks up Google's key rotation
        key = self._keys.get(kid)
        if key is None:
            raise OidcError("invalid_token", f"no Google signing key with kid {kid!r}")
        return key

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",  # let people pick among signed-in accounts
        }
        return f"{self._metadata()['authorization_endpoint']}?{urlencode(params)}"

    def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> OidcIdentity:
        token_endpoint = self._metadata()["token_endpoint"]
        try:
            resp = self._http.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self._client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
                timeout=_HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise OidcError("unavailable", f"token endpoint unreachable: {exc}") from exc
        if resp.status_code != 200:
            # Google explains in {"error", "error_description"}: log it, never show it.
            raise OidcError(
                "exchange_failed", f"token endpoint returned {resp.status_code}: {resp.text[:300]}"
            )
        try:
            id_token = resp.json()["id_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OidcError("exchange_failed", "token response has no id_token") from exc
        claims = verify_id_token(
            id_token,
            key=self._signing_key(id_token),
            issuers=self.ISSUERS,
            audience=self.client_id,
            nonce=nonce,
        )
        return identity_from_claims(self.id, claims)


# --------------------------------------------------------------------------- #
# Development stand-in                                                         #
# --------------------------------------------------------------------------- #
class DevOidcProvider:
    """Stands in for Google so the whole flow runs without real credentials.

    Its authorization endpoint is a page in this app (``/auth/dev-oidc``) where
    you type any email. "Continue" issues a short-lived signed authorization
    code; :meth:`fetch_identity` then checks the redirect URI and PKCE verifier
    like a real token endpoint, mints an RS256 ID token, and verifies it through
    :func:`verify_id_token` — the same checks Google's tokens get.
    """

    id = "google"
    dev_stand_in = True
    CLIENT_ID = "vendor-risk-dev"
    CODE_TTL_SECONDS = 120

    def __init__(self, *, base_url: str) -> None:
        base = base_url.rstrip("/")
        self.issuer = f"{base}/api/v1/auth/dev-oidc"
        self._authorize_endpoint = f"{base}{DEV_AUTHORIZE_PATH}"
        self._lock = threading.Lock()
        self._private_key: rsa.RSAPrivateKey | None = None

    @property
    def _key(self) -> rsa.RSAPrivateKey:
        # Per process is enough: an ID token is minted and verified in one call.
        with self._lock:
            if self._private_key is None:
                self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            return self._private_key

    def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "client_id": self.CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._authorize_endpoint}?{urlencode(params)}"

    def issue_code(
        self,
        *,
        email: str,
        name: str | None,
        email_verified: bool,
        redirect_uri: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        """What the stand-in's login form does on "Continue"."""
        return create_token(
            {
                "type": "dev_oidc_code",
                "email": email,
                "name": name,
                "email_verified": email_verified,
                "redirect_uri": redirect_uri,
                "nonce": nonce,
                "code_challenge": code_challenge,
            },
            self.CODE_TTL_SECONDS,
        )

    def fetch_identity(
        self, *, code: str, code_verifier: str, redirect_uri: str, nonce: str
    ) -> OidcIdentity:
        try:
            grant = decode_token(code)
        except jwt.InvalidTokenError as exc:
            raise OidcError("exchange_failed", f"invalid or expired code: {exc}") from exc
        if grant.get("type") != "dev_oidc_code":
            raise OidcError("exchange_failed", "not an authorization code")
        if grant.get("redirect_uri") != redirect_uri:
            raise OidcError("exchange_failed", "redirect_uri does not match the authorization")
        if not _same(grant.get("code_challenge"), pkce_challenge(code_verifier)):
            raise OidcError("exchange_failed", "PKCE verification failed")

        now = int(time.time())
        email = str(grant["email"]).strip().lower()
        id_token = jwt.encode(
            {
                "iss": self.issuer,
                "aud": self.CLIENT_ID,
                # Stable per email, like a real provider's per-account id.
                "sub": "dev-" + hashlib.sha256(email.encode()).hexdigest()[:24],
                "email": email,
                "email_verified": bool(grant.get("email_verified")),
                "name": grant.get("name"),
                "nonce": grant.get("nonce"),
                "iat": now,
                "exp": now + 300,
            },
            self._key,
            algorithm="RS256",
            headers={"kid": "dev"},
        )
        claims = verify_id_token(
            id_token,
            key=self._key.public_key(),
            issuers=(self.issuer,),
            audience=self.CLIENT_ID,
            nonce=nonce,
        )
        return identity_from_claims(self.id, claims)


# --------------------------------------------------------------------------- #
# Factory                                                                      #
# --------------------------------------------------------------------------- #
def build_provider(settings: Settings) -> OidcProvider | None:
    """Real Google when configured; else the stand-in if allowed; else None."""
    if settings.google_client_id and settings.google_client_secret:
        return GoogleOidcProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            discovery_url=settings.google_discovery_url,
        )
    if settings.google_client_id or settings.google_client_secret:
        log.warning("Google sign-in needs both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    if settings.oidc_dev_provider:
        if settings.is_production:
            log.error("OIDC_DEV_PROVIDER is ignored in production")
            return None
        log.warning(
            "Google sign-in is using the development stand-in: anyone who can "
            "reach this server can sign in as any email address"
        )
        return DevOidcProvider(base_url=settings.app_base_url)
    return None


@lru_cache
def get_provider() -> OidcProvider | None:
    """The process-wide provider (caches Google's discovery document and keys)."""
    return build_provider(get_settings())
