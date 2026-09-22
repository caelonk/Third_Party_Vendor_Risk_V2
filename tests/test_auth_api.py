"""Auth endpoint tests."""

API = "/api/v1"


def test_register_sets_cookies_and_me_works(api):
    client, resp = api.register("a@example.com", name="Ann")
    assert resp.status_code == 201
    assert resp.json()["email"] == "a@example.com"
    assert "access_token" in resp.cookies

    me = client.get(f"{API}/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "a@example.com"


def test_duplicate_email_conflicts(api):
    api.register("dupe@example.com")
    _client, resp = api.register("dupe@example.com")
    assert resp.status_code == 409


def test_login_wrong_password_401(api):
    api.register("b@example.com", password="rightpassword")
    client = api.client()
    resp = client.post(f"{API}/auth/login", json={"email": "b@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_then_me(api):
    api.register("c@example.com", password="password123")
    client = api.client()
    login = client.post(f"{API}/auth/login", json={"email": "c@example.com", "password": "password123"})
    assert login.status_code == 200
    assert client.get(f"{API}/auth/me").status_code == 200


def test_me_requires_auth(api):
    client = api.client()
    assert client.get(f"{API}/auth/me").status_code == 401


def test_logout_clears_session(api):
    client, _ = api.register("d@example.com")
    assert client.get(f"{API}/auth/me").status_code == 200
    assert client.post(f"{API}/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get(f"{API}/auth/me").status_code == 401


def test_refresh_issues_new_access_cookie(api):
    client, _ = api.register("e@example.com")
    # Drop the access cookie but keep refresh; refresh should re-mint access.
    del client.cookies["access_token"]
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.post(f"{API}/auth/refresh").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 200


def test_short_password_rejected(api):
    _client, resp = api.register("f@example.com", password="short")
    assert resp.status_code == 422
