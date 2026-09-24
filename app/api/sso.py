"""Sign in with Google (OIDC authorization code + PKCE).

* ``GET /auth/providers`` — which external sign-ins are enabled (for the SPA).
* ``GET /auth/google/start`` — sets a signed, short-lived flow cookie (state,
  nonce, PKCE verifier, return path) and redirects to the provider.
* ``GET /auth/google/callback`` — checks ``state`` against that cookie,
  exchanges the code, verifies the ID token, resolves the account, sets the
  session cookies, and redirects into the app.

Failures never expose provider details: the browser lands on
``/login?sso_error=<code>`` and the SPA maps the code to a message, while the
detail goes to the logs. The development stand-in's login page lives under
``/auth/dev-oidc`` and is 404 unless the stand-in is the active provider.
"""
from __future__ import annotations

import html
import logging
import re
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..schemas.auth import AuthProviderOut
from ..security import create_token, decode_token
from ..services import oidc, sso_service
from ..services.oidc import DevOidcProvider, OidcError, OidcProvider
from ._cookies import set_auth_cookies

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

FLOW_COOKIE = "oidc_flow"
FLOW_COOKIE_PATH = "/api/v1/auth/"
FLOW_TTL_SECONDS = 600
# Codes the sign-in page explains specifically; anything else is "failed".
_UI_ERRORS = {"unavailable", "unverified", "disabled", "conflict"}
# A same-site path only: "/vendors?x=1" yes; "//evil.com", "/\\evil.com",
# "https://evil.com", "javascript:..." no.
_SAFE_NEXT = re.compile(r"^/(?![/\\])[\x21-\x7E]*$")
_email = TypeAdapter(EmailStr)


def get_oidc_provider() -> OidcProvider | None:
    return oidc.get_provider()


def callback_url() -> str:
    return get_settings().app_base_url.rstrip("/") + oidc.CALLBACK_PATH


def safe_next(value: str | None) -> str:
    if not value or len(value) > 512 or "\\" in value or not _SAFE_NEXT.match(value):
        return "/"
    return value


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def _no_store(resp: RedirectResponse | HTMLResponse) -> None:
    resp.headers["Cache-Control"] = "no-store"


def _clear_flow(resp: RedirectResponse) -> None:
    resp.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH, domain=get_settings().cookie_domain)


def _to_login(code: str) -> RedirectResponse:
    resp = RedirectResponse(f"/login?{urlencode({'sso_error': code})}", status_code=302)
    _clear_flow(resp)
    _no_store(resp)
    return resp


def _read_flow(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        claims = decode_token(token)
    except jwt.InvalidTokenError:  # tampered or older than FLOW_TTL_SECONDS
        return None
    if claims.get("type") != "oidc_flow":
        return None
    if not all(isinstance(claims.get(k), str) for k in ("state", "nonce", "verifier", "next")):
        return None
    return claims


def _require(provider: OidcProvider | None) -> OidcProvider:
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not enabled")
    return provider


@router.get("/providers", response_model=list[AuthProviderOut])
def list_providers(
    provider: OidcProvider | None = Depends(get_oidc_provider),
) -> list[AuthProviderOut]:
    if provider is None:
        return []
    return [AuthProviderOut(id=provider.id, name="Google", dev_stand_in=provider.dev_stand_in)]


@router.get("/google/start")
def google_start(
    request: Request,
    next_path: str | None = Query(default=None, alias="next", max_length=512),
    provider: OidcProvider | None = Depends(get_oidc_provider),
) -> RedirectResponse:
    active = _require(provider)
    base_url = get_settings().app_base_url.rstrip("/")
    base_host = urlsplit(base_url).hostname
    if base_host and request.url.hostname and request.url.hostname != base_host:
        # The flow cookie must live on the host the provider sends the browser
        # back to (e.g. someone opened the app at 127.0.0.1 but the callback is
        # on localhost). Hop to the configured origin first; never to the
        # request's own Host header.
        hop = f"{base_url}{request.url.path}?{urlencode({'next': safe_next(next_path)})}"
        return RedirectResponse(hop, status_code=302)

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = oidc.new_pkce_verifier()
    try:
        url = active.authorization_url(
            redirect_uri=callback_url(),
            state=state,
            nonce=nonce,
            code_challenge=oidc.pkce_challenge(verifier),
        )
    except OidcError as exc:
        log.warning("sso start failed (%s): %s", exc.code, exc, extra={"sso_error": exc.code})
        return _to_login("unavailable")

    settings = get_settings()
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        FLOW_COOKIE,
        create_token(
            {"type": "oidc_flow", "state": state, "nonce": nonce, "verifier": verifier,
             "next": safe_next(next_path)},
            FLOW_TTL_SECONDS,
        ),
        max_age=FLOW_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",  # still sent on the top-level redirect back from Google
        domain=settings.cookie_domain,
        path=FLOW_COOKIE_PATH,
    )
    _no_store(resp)
    return resp


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=200),
    oidc_flow: str | None = Cookie(default=None),
    provider: OidcProvider | None = Depends(get_oidc_provider),
    db: Session = Depends(get_session),
) -> RedirectResponse:
    active = _require(provider)
    if error:
        # "access_denied" = the person cancelled on the provider's page.
        return _to_login("cancelled" if error == "access_denied" else "failed")

    flow = _read_flow(oidc_flow)
    if flow is None or not state or not _same(state, flow["state"]):
        # No cookie (expired, other browser) or a forged/replayed callback.
        log.info("sso callback rejected: missing or mismatched state")
        return _to_login("expired")
    if not code:
        return _to_login("failed")

    try:
        identity = active.fetch_identity(
            code=code, code_verifier=flow["verifier"], redirect_uri=callback_url(),
            nonce=flow["nonce"],
        )
        user, _outcome = sso_service.resolve_user(db, identity)
    except OidcError as exc:
        log.warning("sso sign-in failed (%s): %s", exc.code, exc, extra={"sso_error": exc.code})
        return _to_login(exc.code if exc.code in _UI_ERRORS else "failed")
    except Exception:
        log.exception("sso sign-in failed unexpectedly")
        db.rollback()
        return _to_login("failed")

    resp = RedirectResponse(flow["next"], status_code=302)
    set_auth_cookies(resp, user.id)
    _clear_flow(resp)
    _no_store(resp)
    return resp


# --------------------------------------------------------------------------- #
# Development stand-in: the "provider's" login page                           #
# --------------------------------------------------------------------------- #
_DEV_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)


def _dev_provider(
    provider: OidcProvider | None = Depends(get_oidc_provider),
) -> DevOidcProvider:
    if not isinstance(provider, DevOidcProvider):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return provider


def _check_redirect(redirect_uri: str) -> None:
    # Only ever send codes back to this app's own callback: the stand-in must
    # not become an open redirector.
    if redirect_uri != callback_url():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "redirect_uri is not registered")


def _dev_page(fields: dict[str, str], error: str | None = None) -> HTMLResponse:
    esc = html.escape
    hidden = "".join(
        f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in fields.items()
    )
    alert = f'<p class="err" role="alert">{esc(error)}</p>' if error else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Development sign-in</title>
<style>
  :root {{ --bg:#f5f7fa; --card:#fff; --text:#1a2230; --muted:#5b6675; --border:#d9e0ea;
          --accent:#385ea3; --on-accent:#fff; --danger:#b3261e; color-scheme: light dark; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f141b; --card:#161c25; --text:#e6eaf0; --muted:#98a2b3; --border:#2a3240;
            --accent:#7f9fd6; --on-accent:#0f141b; --danger:#f2b8b5; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         padding:16px;
         background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
  main {{ width:100%; max-width:400px; background:var(--card); border:1px solid var(--border);
         border-radius:10px; padding:28px; }}
  h1 {{ font-size:18px; margin:0 0 6px; }}
  p {{ margin:0 0 18px; color:var(--muted); font-size:13.5px; }}
  .tag {{ display:inline-block; font-size:11px; font-weight:600; letter-spacing:.04em;
         text-transform:uppercase; color:var(--muted); border:1px solid var(--border);
         border-radius:999px; padding:2px 9px; margin-bottom:14px; }}
  label {{ display:block; font-size:13px; font-weight:600; margin:0 0 6px; }}
  input[type=email], input[type=text] {{ width:100%; height:38px; padding:0 10px; font:inherit;
         color:inherit; background:var(--bg); border:1px solid var(--border); border-radius:6px;
         margin-bottom:14px; }}
  .check {{ display:flex; gap:8px; align-items:center; font-weight:400; margin-bottom:20px; }}
  .row {{ display:flex; gap:10px; }}
  button {{ flex:1; height:38px; font:inherit; font-weight:600; border-radius:6px; cursor:pointer;
           border:1px solid var(--border); background:var(--card); color:var(--text); }}
  button.primary {{ background:var(--accent); border-color:var(--accent); color:var(--on-accent); }}
  .err {{ color:var(--danger); }}
</style></head>
<body><main>
  <span class="tag">Development stand-in</span>
  <h1>Sign in as a test user</h1>
  <p>This page stands in for Google because no Google credentials are configured.
     Any email works and no real Google account is involved. It is never available
     in production.</p>
  {alert}
  <form method="get" action="/api/v1/auth/dev-oidc/approve">
    {hidden}
    <label for="email">Email</label>
    <input id="email" name="email" type="email" required autofocus autocomplete="email">
    <label for="name">Name (optional)</label>
    <input id="name" name="name" type="text" maxlength="200" autocomplete="name">
    <label class="check"><input type="checkbox" name="email_verified" value="on" checked>
      The provider has verified this email</label>
    <div class="row">
      <button type="submit" name="action" value="cancel" formnovalidate>Cancel</button>
      <button type="submit" name="action" value="approve" class="primary">Continue</button>
    </div>
  </form>
</main></body></html>"""
    resp = HTMLResponse(page, status_code=422 if error else 200)
    resp.headers["Content-Security-Policy"] = _DEV_CSP
    _no_store(resp)
    return resp


@router.get("/dev-oidc/authorize", response_class=HTMLResponse, include_in_schema=False)
def dev_authorize(
    client_id: str = Query(..., max_length=100),
    redirect_uri: str = Query(..., max_length=512),
    state: str = Query(..., max_length=512),
    nonce: str = Query(..., max_length=512),
    code_challenge: str = Query(..., max_length=128),
    code_challenge_method: str = Query(default="S256", max_length=10),
    _dev: DevOidcProvider = Depends(_dev_provider),
) -> HTMLResponse:
    if client_id != DevOidcProvider.CLIENT_ID or code_challenge_method != "S256":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported client or PKCE method")
    _check_redirect(redirect_uri)
    return _dev_page(
        {"redirect_uri": redirect_uri, "state": state, "nonce": nonce,
         "code_challenge": code_challenge}
    )


@router.get("/dev-oidc/approve", include_in_schema=False, response_model=None)
def dev_approve(
    redirect_uri: str = Query(..., max_length=512),
    state: str = Query(..., max_length=512),
    nonce: str = Query(..., max_length=512),
    code_challenge: str = Query(..., max_length=128),
    action: str = Query(default="approve", max_length=20),
    email: str = Query(default="", max_length=320),
    name: str = Query(default="", max_length=200),
    email_verified: str | None = Query(default=None, max_length=10),
    dev: DevOidcProvider = Depends(_dev_provider),
) -> RedirectResponse | HTMLResponse:
    _check_redirect(redirect_uri)
    if action == "cancel":
        target = f"{redirect_uri}?{urlencode({'error': 'access_denied', 'state': state})}"
        return RedirectResponse(target, status_code=302)
    try:
        address = str(_email.validate_python(email.strip()))
    except PydanticValidationError:
        return _dev_page(
            {"redirect_uri": redirect_uri, "state": state, "nonce": nonce,
             "code_challenge": code_challenge},
            error="Enter a valid email address.",
        )
    code = dev.issue_code(
        email=address,
        name=name.strip() or None,
        email_verified=email_verified is not None,
        redirect_uri=redirect_uri,
        nonce=nonce,
        code_challenge=code_challenge,
    )
    resp = RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}",
                            status_code=302)
    _no_store(resp)
    return resp
