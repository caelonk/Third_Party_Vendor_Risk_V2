"""Sign-in methods in Settings: unlink Google, then create a password; change an
existing password by proving the current one. The unlink-first rule is enforced
by the API, not only by the greyed-out form."""
from app.models import User, UserIdentity
from app.security import create_access_token
from app.services import sso_service
from app.services.oidc import OidcIdentity

API = "/api/v1"


def _google_only_client(api, email="gonly@example.com"):
    """A user created by a first Google sign-in (no password), signed in."""
    with api.db() as db:
        user, outcome = sso_service.resolve_user(
            db, OidcIdentity("google", "sub-" + email, email, True, "G Only")
        )
        assert outcome == "created"
        uid = user.id
    client = api.client()
    client.cookies.set("access_token", create_access_token(uid))
    return client


def _login(api, email, password):
    return api.client().post(f"{API}/auth/login", json={"email": email, "password": password})


def test_google_account_must_unlink_before_creating_a_password(api):
    client = _google_only_client(api)
    methods = client.get(f"{API}/me/sign-in-methods").json()
    assert methods["has_password"] is False
    assert [(i["provider"], i["email"]) for i in methods["identities"]] == [
        ("google", "gonly@example.com")
    ]
    assert methods["identities"][0]["linked_at"]

    # Still linked: the API refuses, whatever the UI shows.
    res = client.put(f"{API}/me/password", json={"new_password": "brand-new-pw"})
    assert res.status_code == 409
    assert "Unlink Google" in res.json()["detail"]

    unlinked = client.delete(f"{API}/me/identities/google")
    assert unlinked.status_code == 200
    assert unlinked.json() == {"has_password": False, "identities": []}
    # This session stays valid after unlinking...
    assert client.get(f"{API}/auth/me").status_code == 200
    # ...and can now create the password (no current password to prove).
    assert client.put(f"{API}/me/password", json={"new_password": "brand-new-pw"}).status_code == 204

    assert client.get(f"{API}/me/sign-in-methods").json()["has_password"] is True
    assert _login(api, "gonly@example.com", "brand-new-pw").status_code == 200


def test_signing_in_with_google_after_unlinking_links_it_again(api):
    client = _google_only_client(api, "back@example.com")
    client.delete(f"{API}/me/identities/google")
    with api.db() as db:
        _user, outcome = sso_service.resolve_user(
            db, OidcIdentity("google", "sub-back@example.com", "back@example.com", True, None)
        )
        assert outcome == "linked"
        assert db.query(UserIdentity).count() == 1


def test_changing_a_password_requires_the_current_one(api):
    client, _ = api.register("pw@acme.io")
    url = f"{API}/me/password"
    assert client.put(url, json={"new_password": "another-pw-1"}).status_code == 422
    wrong = client.put(url, json={"current_password": "nope-nope", "new_password": "another-pw-1"})
    assert wrong.status_code == 422 and "incorrect" in wrong.json()["detail"]
    same = client.put(url, json={"current_password": "password123", "new_password": "password123"})
    assert same.status_code == 422 and "differs" in same.json()["detail"]

    ok = client.put(url, json={"current_password": "password123", "new_password": "another-pw-1"})
    assert ok.status_code == 204
    assert _login(api, "pw@acme.io", "password123").status_code == 401
    assert _login(api, "pw@acme.io", "another-pw-1").status_code == 200


def test_password_account_can_unlink_google_and_keep_its_password(api):
    client, _ = api.register("both@acme.io")
    with api.db() as db:
        sso_service.resolve_user(db, OidcIdentity("google", "sub-both", "both@acme.io", True, None))
    methods = client.get(f"{API}/me/sign-in-methods").json()
    assert methods["has_password"] is True and len(methods["identities"]) == 1

    assert client.delete(f"{API}/me/identities/google").json()["identities"] == []
    assert _login(api, "both@acme.io", "password123").status_code == 200


def test_unlinking_something_not_linked_is_404(api):
    client, _ = api.register("none@acme.io")
    res = client.delete(f"{API}/me/identities/google")
    assert res.status_code == 404
    assert client.delete(f"{API}/me/identities/NOT_A_PROVIDER").status_code == 422


def test_new_password_rules_and_auth(api):
    client = _google_only_client(api, "rules@example.com")
    client.delete(f"{API}/me/identities/google")
    assert client.put(f"{API}/me/password", json={"new_password": "short"}).status_code == 422
    anon = api.client()
    assert anon.get(f"{API}/me/sign-in-methods").status_code == 401
    assert anon.put(f"{API}/me/password", json={"new_password": "long-enough"}).status_code == 401
    assert anon.delete(f"{API}/me/identities/google").status_code == 401
    with api.db() as db:
        assert db.query(User).filter_by(email="rules@example.com").one().password_hash is None
