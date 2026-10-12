"""The profile page's API: display name, photo upload, recent sign-ins, and the
member details (employee ID, team) an org's admins record."""
import io

import pytest
from PIL import Image

from app.api.me import get_avatar_storage
from app.models import LoginEvent, Role, User
from app.services import org_service, profile_service
from app.services.object_storage import LocalStorage

API = "/api/v1"


@pytest.fixture
def storage(api, tmp_path):
    store = LocalStorage(tmp_path / "files", secret="test-secret")
    api.app.dependency_overrides[get_avatar_storage] = lambda: store
    return store


def _image(fmt="PNG", size=(640, 480), color=(40, 90, 160), **save_kwargs) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt, **save_kwargs)
    return out.getvalue()


def _upload(client, data: bytes, content_type="image/png"):
    return client.put(f"{API}/me/avatar", content=data, headers={"Content-Type": content_type})


def _org(client) -> dict:
    return client.get(f"{API}/orgs").json()[0]


def _join(api, org_id: int, email: str, role: Role = Role.member):
    """Register a second user and add them to ``org_id``."""
    client, res = api.register(email)
    with api.db() as db:
        org_service.add_member(db, org_id, user_id=res.json()["id"], role=role)
    return client, res.json()["id"]


# --------------------------------------------------------------------------- #
# Display name                                                                 #
# --------------------------------------------------------------------------- #
def test_change_display_name(api):
    client, _ = api.register("name@acme.io", name="Old Name")
    res = client.patch(f"{API}/me", json={"name": "  New   Name  "})
    assert res.status_code == 200
    assert res.json()["name"] == "New Name"  # trimmed, inner whitespace collapsed
    assert client.get(f"{API}/auth/me").json()["name"] == "New Name"


def test_blank_display_name_clears_it(api):
    client, _ = api.register("blank@acme.io", name="Someone")
    assert client.patch(f"{API}/me", json={"name": "   "}).json()["name"] is None


def test_display_name_length_is_capped(api):
    client, _ = api.register("long@acme.io")
    assert client.patch(f"{API}/me", json={"name": "x" * 201}).status_code == 422


def test_profile_requires_a_session(api):
    assert api.client().patch(f"{API}/me", json={"name": "x"}).status_code == 401
    assert api.client().get(f"{API}/me/logins").status_code == 401
    assert api.client().get(f"{API}/me/avatar").status_code == 401


# --------------------------------------------------------------------------- #
# Photo                                                                        #
# --------------------------------------------------------------------------- #
def test_upload_stores_a_small_square_webp(api, storage):
    client, _ = api.register("pic@acme.io")
    assert client.get(f"{API}/auth/me").json()["avatar_url"] is None

    res = _upload(client, _image())
    assert res.status_code == 200, res.text
    url = res.json()["avatar_url"]
    assert url.startswith(f"{API}/me/avatar?v=")
    assert "avatar_key" not in res.json()  # the storage key stays on the server

    served = client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert "private" in served.headers["cache-control"]
    assert served.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(served.content)) as img:
        assert img.format == "WEBP" and img.size == (256, 256)


@pytest.mark.parametrize(
    ("fmt", "content_type"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_png_jpeg_and_webp_are_accepted(api, storage, fmt, content_type):
    client, _ = api.register(f"{fmt.lower()}@acme.io")
    assert _upload(client, _image(fmt), content_type).status_code == 200


def test_replacing_a_photo_changes_the_url_and_deletes_the_old_file(api, storage):
    client, res = api.register("swap@acme.io")
    first = _upload(client, _image()).json()["avatar_url"]
    second = _upload(client, _image(color=(200, 30, 30))).json()["avatar_url"]
    assert first != second
    files = [p for p in (storage.root / "avatars" / str(res.json()["id"])).iterdir()]
    assert len(files) == 1


def test_removing_a_photo(api, storage):
    client, res = api.register("gone@acme.io")
    _upload(client, _image())
    removed = client.delete(f"{API}/me/avatar")
    assert removed.status_code == 200 and removed.json()["avatar_url"] is None
    assert client.get(f"{API}/me/avatar").status_code == 404
    assert not list((storage.root / "avatars" / str(res.json()["id"])).iterdir())


def test_metadata_is_stripped_from_the_stored_photo(api, storage):
    client, _ = api.register("exif@acme.io")
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"  # Make
    res = _upload(client, _image("JPEG", exif=exif.tobytes()), "image/jpeg")
    served = client.get(res.json()["avatar_url"]).content
    assert b"SecretCameraMaker" not in served
    with Image.open(io.BytesIO(served)) as img:
        assert not img.getexif()


def test_a_sideways_phone_photo_is_stored_upright(api, storage):
    client, _ = api.register("rotate@acme.io")
    # Left half red, right half blue, flagged "rotate 90 degrees clockwise to view".
    img = Image.new("RGB", (400, 200), (220, 20, 20))
    img.paste((20, 20, 220), (200, 0, 400, 200))
    exif = Image.Exif()
    exif[0x0112] = 6
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes(), quality=95)
    res = _upload(client, out.getvalue(), "image/jpeg")
    with Image.open(io.BytesIO(client.get(res.json()["avatar_url"]).content)) as stored:
        top, bottom = stored.convert("RGB").getpixel((128, 20)), stored.convert("RGB").getpixel((128, 236))
    assert top[0] > 150 and top[2] < 100      # red ended up on top
    assert bottom[2] > 150 and bottom[0] < 100  # blue at the bottom


def test_a_file_that_is_not_an_image_is_refused(api, storage):
    client, _ = api.register("fake@acme.io")
    res = _upload(client, b"<html><script>alert(1)</script></html>")
    assert res.status_code == 422 and "PNG, JPEG or WebP" in res.json()["detail"]
    assert client.get(f"{API}/auth/me").json()["avatar_url"] is None


def test_only_the_three_formats_are_decoded(api, storage):
    client, _ = api.register("gif@acme.io")
    # A real GIF, declared as PNG: the bytes decide, not the header.
    assert _upload(client, _image("GIF"), "image/png").status_code == 422
    # ...and a declared type outside the list is refused before decoding.
    assert _upload(client, _image("GIF"), "image/gif").status_code == 415
    assert _upload(client, _image(), "text/plain").status_code == 415


def test_truncated_image_is_refused(api, storage):
    client, _ = api.register("cut@acme.io")
    assert _upload(client, _image("JPEG")[:200], "image/jpeg").status_code == 422


def test_oversized_upload_is_refused(api, storage, monkeypatch):
    client, _ = api.register("big@acme.io")
    monkeypatch.setattr(profile_service, "MAX_AVATAR_BYTES", 1000)
    data = _image("PNG", size=(900, 900)) + b"\0" * 2000
    assert _upload(client, data).status_code == 413  # by declared length
    # The same bytes with no usable length header are still refused by the service.
    with pytest.raises(profile_service.ValidationError, match="larger than"):
        profile_service.process_avatar(data)


def test_huge_dimensions_are_refused_before_decoding(api, storage):
    client, _ = api.register("bomb@acme.io")
    out = io.BytesIO()
    Image.new("1", (7000, 7000)).save(out, "PNG")  # 49 MP in a few KB
    assert len(out.getvalue()) < 50_000
    res = _upload(client, out.getvalue())
    assert res.status_code == 422 and "dimensions" in res.json()["detail"]


def test_transparent_images_keep_their_transparency(api, storage):
    client, _ = api.register("alpha@acme.io")
    out = io.BytesIO()
    Image.new("RGBA", (300, 300), (0, 0, 0, 0)).save(out, "PNG")
    res = _upload(client, out.getvalue())
    with Image.open(io.BytesIO(client.get(res.json()["avatar_url"]).content)) as img:
        assert img.convert("RGBA").getpixel((10, 10))[3] == 0


def test_members_can_see_each_others_photos_but_outsiders_cannot(api, storage):
    owner, res = api.register("owner@acme.io")
    owner_id, org_id = res.json()["id"], _org(owner)["id"]
    _upload(owner, _image())
    teammate, _ = _join(api, org_id, "mate@acme.io")
    outsider, _ = api.register("else@other.io")

    listed = {m["email"]: m for m in teammate.get(f"{API}/orgs/{org_id}/members").json()}
    url = listed["owner@acme.io"]["avatar_url"]
    assert url.startswith(f"{API}/orgs/{org_id}/members/{owner_id}/avatar?v=")
    assert listed["mate@acme.io"]["avatar_url"] is None
    assert teammate.get(url).status_code == 200
    assert outsider.get(url).status_code == 404  # not a member: the org does not exist to them

    # Through an org the photo's owner is not in, it cannot be fetched either.
    outsider_org = _org(outsider)["id"]
    assert outsider.get(f"{API}/orgs/{outsider_org}/members/{owner_id}/avatar").status_code == 404


# --------------------------------------------------------------------------- #
# Recent sign-ins                                                              #
# --------------------------------------------------------------------------- #
def _login(api, email, password="password123", **headers):
    return api.client().post(
        f"{API}/auth/login", json={"email": email, "password": password}, headers=headers
    )


def test_registering_and_signing_in_are_recorded(api):
    client, _ = api.register("log@acme.io")
    assert _login(api, "log@acme.io", **{"User-Agent": "Mozilla/5.0 TestBrowser"}).status_code == 200

    events = client.get(f"{API}/me/logins").json()
    assert [e["method"] for e in events] == ["password", "password"]
    assert events[0]["user_agent"] == "Mozilla/5.0 TestBrowser"  # newest first
    assert events[0]["ip"] == "testclient"
    assert events[0]["created_at"] >= events[1]["created_at"]


def test_a_failed_sign_in_is_not_recorded(api):
    client, _ = api.register("fail@acme.io")
    assert _login(api, "fail@acme.io", "wrong-password").status_code == 401
    assert len(client.get(f"{API}/me/logins").json()) == 1  # just the registration


def test_only_the_last_five_are_shown_and_old_ones_are_pruned(api):
    client, res = api.register("many@acme.io")
    with api.db() as db:
        user = db.get(User, res.json()["id"])
        for i in range(30):
            profile_service.record_login(db, user, method="password", ip=f"10.0.0.{i}", user_agent=None)
        assert db.query(LoginEvent).filter_by(user_id=user.id).count() == profile_service.LOGIN_HISTORY_KEEP

    shown = client.get(f"{API}/me/logins").json()
    assert [e["ip"] for e in shown] == ["10.0.0.29", "10.0.0.28", "10.0.0.27", "10.0.0.26", "10.0.0.25"]
    assert len(client.get(f"{API}/me/logins", params={"limit": 20}).json()) == 20
    assert client.get(f"{API}/me/logins", params={"limit": 21}).status_code == 422


def test_sign_ins_are_private_to_each_user(api):
    a, _ = api.register("a@acme.io")
    b, _ = api.register("b@acme.io")
    _login(api, "a@acme.io")
    assert len(a.get(f"{API}/me/logins").json()) == 2
    assert len(b.get(f"{API}/me/logins").json()) == 1


def test_overlong_browser_strings_are_truncated(api):
    client, _ = api.register("ua@acme.io")
    _login(api, "ua@acme.io", **{"User-Agent": "x" * 2000})
    assert len(client.get(f"{API}/me/logins").json()[0]["user_agent"]) == 300


def test_a_recording_failure_never_blocks_signing_in(api, monkeypatch):
    api.register("sturdy@acme.io")

    def boom(*_args, **_kwargs):
        raise RuntimeError("history table unavailable")

    monkeypatch.setattr(profile_service, "LoginEvent", boom)
    assert _login(api, "sturdy@acme.io").status_code == 200


# --------------------------------------------------------------------------- #
# Member details set by admins                                                 #
# --------------------------------------------------------------------------- #
def test_admin_sets_employee_id_and_team_and_the_member_sees_them(api):
    owner, _ = api.register("lead@acme.io")
    org_id = _org(owner)["id"]
    member, member_id = _join(api, org_id, "dev@acme.io")
    assert {"employee_id": None, "team": None}.items() <= _org(owner).items()

    res = owner.patch(
        f"{API}/orgs/{org_id}/members/{member_id}",
        json={"employee_id": "  E-1042 ", "team": "Platform"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["employee_id"] == "E-1042" and res.json()["team"] == "Platform"
    assert res.json()["role"] == "member"  # untouched

    mine = next(o for o in member.get(f"{API}/orgs").json() if o["id"] == org_id)
    assert (mine["employee_id"], mine["team"]) == ("E-1042", "Platform")
    # They are per organization: the member's own personal org has none.
    other = next(o for o in member.get(f"{API}/orgs").json() if o["id"] != org_id)
    assert other["employee_id"] is None and other["team"] is None


def test_blank_clears_and_absent_fields_are_left_alone(api):
    owner, _ = api.register("lead2@acme.io")
    org_id = _org(owner)["id"]
    _, member_id = _join(api, org_id, "dev2@acme.io")
    url = f"{API}/orgs/{org_id}/members/{member_id}"
    owner.patch(url, json={"employee_id": "77", "team": "Risk"})

    cleared = owner.patch(url, json={"team": ""}).json()
    assert cleared["team"] is None and cleared["employee_id"] == "77"
    assert owner.patch(url, json={}).json() == cleared  # an empty patch changes nothing


def test_employee_id_is_unique_within_an_org(api):
    owner, res = api.register("lead3@acme.io")
    org_id = _org(owner)["id"]
    _, member_id = _join(api, org_id, "dev3@acme.io")
    owner.patch(f"{API}/orgs/{org_id}/members/{res.json()['id']}", json={"employee_id": "A-1"})

    clash = owner.patch(f"{API}/orgs/{org_id}/members/{member_id}", json={"employee_id": "a-1"})
    assert clash.status_code == 409 and "lead3@acme.io" in clash.json()["detail"]
    # Saving the same value on the member who already has it is fine.
    same = owner.patch(f"{API}/orgs/{org_id}/members/{res.json()['id']}", json={"employee_id": "A-1"})
    assert same.status_code == 200

    # The same ID in a different organization does not clash.
    other, other_res = api.register("solo@else.io")
    ok = other.patch(
        f"{API}/orgs/{_org(other)['id']}/members/{other_res.json()['id']}", json={"employee_id": "A-1"}
    )
    assert ok.status_code == 200


def test_only_admins_can_edit_member_details(api):
    owner, res = api.register("lead4@acme.io")
    org_id = _org(owner)["id"]
    member, member_id = _join(api, org_id, "dev4@acme.io")
    url = f"{API}/orgs/{org_id}/members/{member_id}"
    assert member.patch(url, json={"team": "Mine"}).status_code == 403
    outsider, _ = api.register("nope@else.io")
    assert outsider.patch(url, json={"team": "Theirs"}).status_code == 404
    assert owner.patch(f"{API}/orgs/{org_id}/members/999999", json={"team": "x"}).status_code == 404
    assert owner.patch(url, json={"employee_id": "x" * 65}).status_code == 422


def test_role_and_details_can_change_together_and_both_are_audited(api):
    owner, _ = api.register("lead5@acme.io")
    org_id = _org(owner)["id"]
    _, member_id = _join(api, org_id, "dev5@acme.io")
    res = owner.patch(
        f"{API}/orgs/{org_id}/members/{member_id}", json={"role": "admin", "team": "SecOps"}
    )
    assert res.status_code == 200
    assert (res.json()["role"], res.json()["team"]) == ("admin", "SecOps")

    log = owner.get(f"{API}/orgs/{org_id}/audit-log").json()
    actions = {e["action"]: e["extra"] for e in log}
    assert actions["member.role_changed"]["role"] == "admin"
    assert actions["member.updated"] == {"email": "dev5@acme.io", "fields": ["team"]}

    # Re-sending the same values changes nothing and adds no audit noise.
    owner.patch(f"{API}/orgs/{org_id}/members/{member_id}", json={"role": "admin", "team": "SecOps"})
    assert len(owner.get(f"{API}/orgs/{org_id}/audit-log").json()) == len(log)
