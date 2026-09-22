"""Organization, membership, RBAC, and invitation tests."""

API = "/api/v1"


def _personal_org(client) -> dict:
    orgs = client.get(f"{API}/orgs").json()
    assert orgs, "expected a personal org from registration"
    return orgs[0]


def test_registration_creates_personal_owner_org(api):
    client, _ = api.register("owner@example.com", name="Owner")
    org = _personal_org(client)
    assert org["role"] == "owner"
    assert org["name"] == "Owner's Organization"


def test_create_additional_org(api):
    client, _ = api.register("x@example.com")
    resp = client.post(f"{API}/orgs", json={"name": "Second Co"})
    assert resp.status_code == 201
    assert resp.json()["slug"] == "second-co"


def test_non_member_cannot_see_org(api):
    c1, _ = api.register("u1@example.com")
    c2, _ = api.register("u2@example.com")
    org2 = _personal_org(c2)
    assert c1.get(f"{API}/orgs/{org2['id']}").status_code == 404


def test_members_list_includes_owner(api):
    client, _ = api.register("m@example.com")
    org = _personal_org(client)
    members = client.get(f"{API}/orgs/{org['id']}/members").json()
    assert [m["email"] for m in members] == ["m@example.com"]
    assert members[0]["role"] == "owner"


def test_invitation_flow_and_rbac(api):
    owner, _ = api.register("boss@example.com")
    org = _personal_org(owner)

    invitee, _ = api.register("staff@example.com")

    # Owner invites the staff member as a viewer.
    inv = owner.post(
        f"{API}/orgs/{org['id']}/invitations",
        json={"email": "staff@example.com", "role": "viewer"},
    )
    assert inv.status_code == 201
    token = inv.json()["token"]

    # Staff accepts and becomes a viewer member.
    accepted = invitee.post(f"{API}/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "viewer"

    # A viewer cannot issue invitations (RBAC requires admin+).
    forbidden = invitee.post(
        f"{API}/orgs/{org['id']}/invitations",
        json={"email": "someone@example.com", "role": "member"},
    )
    assert forbidden.status_code == 403


def test_cannot_remove_last_owner(api):
    client, _ = api.register("solo@example.com")
    org = _personal_org(client)
    me = client.get(f"{API}/auth/me").json()
    resp = client.request("DELETE", f"{API}/orgs/{org['id']}/members/{me['id']}")
    assert resp.status_code == 409


def test_invitation_to_wrong_email_denied(api):
    owner, _ = api.register("boss2@example.com")
    org = _personal_org(owner)
    other, _ = api.register("other@example.com")
    inv = owner.post(
        f"{API}/orgs/{org['id']}/invitations",
        json={"email": "intended@example.com", "role": "member"},
    )
    token = inv.json()["token"]
    # 'other@example.com' holds the token but it was issued to another email.
    assert other.post(f"{API}/invitations/accept", json={"token": token}).status_code == 403
