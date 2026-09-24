"""SBOM import API: preview statuses, import dedupe, RBAC, audit, and that
imported vendors are picked up by scheduled sync."""
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.sbom import MAX_SBOM_BYTES, _limit_size
from app.services import scheduled_sync_service as sched

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "sbom"


def _doc(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def test_preview_marks_new_and_existing(api):
    client, _ = api.register("sb@acme.io")
    oid = _org_id(client)
    # Already present: one by CPE prefix (different name), one by name (unmapped).
    client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Our Log4j", "cpe_prefix": "cpe:2.3:a:apache:log4j"})
    client.post(f"{API}/orgs/{oid}/vendors", json={"name": "Lodash"})

    res = client.post(f"{API}/orgs/{oid}/sbom/preview", json=_doc("cyclonedx.json"))
    assert res.status_code == 200
    body = res.json()
    assert body["format"] == "cyclonedx" and body["subject"] == "acme-portal"
    assert body["component_count"] == 9
    status = {c["name"]: c["status"] for c in body["candidates"]}
    assert status["Apache Log4j"] == "exists"  # matched by prefix
    assert status["lodash"] == "exists"  # matched by name, case-insensitively
    assert status["Openssl"] == "new"


def test_preview_flags_in_file_duplicates(api):
    client, _ = api.register("sb2@acme.io")
    oid = _org_id(client)
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [
            {"type": "library", "name": "zlib", "cpe": "cpe:/a:zlib:zlib:1.2.13"},
            {"type": "library", "name": "Zlib"},  # no CPE, same display name
        ],
    }
    cands = client.post(f"{API}/orgs/{oid}/sbom/preview", json=doc).json()["candidates"]
    assert [(c["name"], c["cpe_prefix"], c["status"]) for c in cands] == [
        ("Zlib", "cpe:2.3:a:zlib:zlib", "new"),
        ("Zlib", None, "duplicate"),
    ]


def test_preview_rejects_non_sbom_with_a_clear_message(api):
    client, _ = api.register("sb3@acme.io")
    oid = _org_id(client)
    res = client.post(f"{API}/orgs/{oid}/sbom/preview", json={"hello": "world"})
    assert res.status_code == 422
    assert "CycloneDX or SPDX" in res.json()["detail"]
    # A JSON array is not an SBOM object either.
    assert client.post(f"{API}/orgs/{oid}/sbom/preview", json=[1, 2]).status_code == 422


def test_size_guard():
    _limit_size(MAX_SBOM_BYTES)  # at the limit: fine
    with pytest.raises(HTTPException) as exc:
        _limit_size(MAX_SBOM_BYTES + 1)
    assert exc.value.status_code == 413


def test_import_creates_unassessed_vendors_and_skips_existing(api):
    client, _ = api.register("sb4@acme.io")
    oid = _org_id(client)
    client.post(f"{API}/orgs/{oid}/vendors", json={"name": "F5 Nginx"})

    res = client.post(
        f"{API}/orgs/{oid}/sbom/import",
        json={"items": [
            {"name": "F5 Nginx", "cpe_prefix": "cpe:2.3:a:f5:nginx"},  # exists by name
            {"name": "Zlib", "cpe_prefix": "cpe:2.3:a:zlib:zlib"},
            {"name": "requests", "cpe_prefix": None},
            {"name": "Bogus", "cpe_prefix": "not-a-cpe"},
            {"name": "zlib", "cpe_prefix": "cpe:2.3:a:zlib:zlib"},  # repeat within batch
        ]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 2 and body["names"] == ["Zlib", "requests"]
    assert {(s["name"], s["reason"]) for s in body["skipped"]} == {
        ("F5 Nginx", "exists"),
        ("Bogus", "invalid_cpe"),
        ("zlib", "exists"),
    }

    vendors = {v["name"]: v for v in client.get(f"{API}/orgs/{oid}/vendors").json()}
    assert vendors["Zlib"]["cpe_prefix"] == "cpe:2.3:a:zlib:zlib"
    # Honest: imported but not yet synced -> Not Assessed, never "Low".
    assert vendors["Zlib"]["assessment"]["tier"] == "Not Assessed"
    assert vendors["requests"]["cpe_prefix"] is None

    log = client.get(f"{API}/orgs/{oid}/audit-log").json()
    entry = next(e for e in log if e["action"] == "vendor.imported")
    assert entry["extra"] == {"source": "sbom", "created": 2, "skipped": 3}


def test_imported_mapped_vendor_is_due_for_scheduled_sync(api):
    client, _ = api.register("sb5@acme.io")
    oid = _org_id(client)
    client.post(
        f"{API}/orgs/{oid}/sbom/import",
        json={"items": [{"name": "Zlib", "cpe_prefix": "cpe:2.3:a:zlib:zlib"}, {"name": "requests"}]},
    )
    with api.db() as db:
        due = {v.name for v in sched.select_due_vendors(db, datetime(2030, 1, 1))}
    assert "Zlib" in due  # picked up without a manual Sync click
    assert "requests" not in due  # no CPE -> nothing to sync


def test_import_batch_cap(api):
    client, _ = api.register("sb6@acme.io")
    oid = _org_id(client)
    items = [{"name": f"pkg-{i}"} for i in range(501)]
    assert client.post(f"{API}/orgs/{oid}/sbom/import", json={"items": items}).status_code == 422


def test_viewer_cannot_preview_or_import(api):
    owner, _ = api.register("sb-o@acme.io")
    oid = _org_id(owner)
    token = owner.post(
        f"{API}/orgs/{oid}/invitations", json={"email": "sb-v@acme.io", "role": "viewer"}
    ).json()["token"]
    viewer, _ = api.register("sb-v@acme.io")
    viewer.post(f"{API}/invitations/accept", json={"token": token})

    assert viewer.post(f"{API}/orgs/{oid}/sbom/preview", json=_doc("spdx.json")).status_code == 403
    assert viewer.post(
        f"{API}/orgs/{oid}/sbom/import", json={"items": [{"name": "x"}]}
    ).status_code == 403
