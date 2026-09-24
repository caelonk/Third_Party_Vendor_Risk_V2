"""Background export jobs: queue -> render into object storage -> signed download.

Runs against LocalStorage in a temp dir (the dev/test backend with the same
signed-URL contract as S3) and an inline dispatcher standing in for Celery. The
S3 backend is unit-tested offline: presigning needs no network, and botocore's
Stubber checks the calls a real bucket would receive.
"""
import csv
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber

from app.api.exports import get_export_dispatcher, get_export_storage
from app.config import Settings, get_settings
from app.models import (
    ExportFormat,
    ExportJob,
    ExportStatus,
    Membership,
    Role,
    User,
    Vendor,
    VendorVulnerability,
    Vulnerability,
)
from app.services import export_service
from app.services.object_storage import (
    LocalStorage,
    S3Storage,
    build_storage,
    check_key,
    content_disposition,
)
from core.constants import SCOPE_DISCLAIMER

API = "/api/v1"


class Harness:
    """The API harness plus local storage and a switchable job dispatcher."""

    def __init__(self, api, tmp_path):
        self.api = api
        self.storage = LocalStorage(tmp_path / "exports", secret="test-secret")
        self.mode = "inline"  # inline | record | fail
        self.dispatched: list[int] = []
        api.app.dependency_overrides[get_export_storage] = lambda: self.storage
        api.app.dependency_overrides[get_export_dispatcher] = lambda: self._dispatch

    def _dispatch(self, job_id: int) -> None:
        self.dispatched.append(job_id)
        if self.mode == "fail":
            raise ConnectionError("broker down")
        if self.mode == "inline":
            self.run(job_id)

    def run(self, job_id: int, **kwargs):
        with self.api.db() as db:
            return export_service.run_job(db, job_id, self.storage, **kwargs)

    def files(self) -> list[str]:
        root = self.storage.root
        if not root.exists():
            return []
        return sorted(
            str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
        )


@pytest.fixture
def ex(api, tmp_path):
    return Harness(api, tmp_path)


def _seed(api, email="jobs@acme.io"):
    client, _ = api.register(email, org_name="Acme")
    oid = client.get(f"{API}/orgs").json()[0]["id"]
    with api.db() as db:
        db.add(Vendor(org_id=oid, name="Alpha Unmapped", is_mapped=False))
        beta = Vendor(org_id=oid, name="Beta Scored", is_mapped=True, cpe_prefix="cpe:2.3:a:x:y")
        db.add(beta)
        db.flush()
        db.add(Vulnerability(cve_id="CVE-2024-9001", cvss_score=9.1, is_kev=True))
        db.flush()
        db.add(VendorVulnerability(vendor_id=beta.id, cve_id="CVE-2024-9001"))
        db.commit()
    return client, oid


def _create(client, oid, fmt="csv"):
    return client.post(f"{API}/orgs/{oid}/exports", json={"format": fmt})


def _download(client, oid, job_id):
    """Follow the API redirect to the signed URL; return (redirect, file response)."""
    redirect = client.get(f"{API}/orgs/{oid}/exports/{job_id}/download", follow_redirects=False)
    if redirect.status_code != 302:
        return redirect, None
    return redirect, client.get(redirect.headers["location"])


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #
def test_csv_export_job_renders_stores_and_downloads(api, ex):
    client, oid = _seed(api)
    res = _create(client, oid)
    assert res.status_code == 202
    job = res.json()
    assert job["status"] == "succeeded"
    assert job["format"] == "csv"
    assert job["filename"].endswith(".csv") and "acme" in job["filename"]
    assert job["size_bytes"] > 0
    assert job["requested_by"] == "jobs@acme.io"
    assert job["expires_at"]

    redirect, file = _download(client, oid, job["id"])
    assert redirect.headers["cache-control"] == "no-store"
    assert redirect.headers["location"].startswith(f"{LocalStorage.URL_PREFIX}/exports/{oid}/")
    assert file.status_code == 200
    assert file.headers["content-type"].startswith("text/csv")
    assert "attachment" in file.headers["content-disposition"]
    assert job["filename"] in file.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(file.content.decode("utf-8"))))
    # The scope disclaimer rides along verbatim (locked integrity rule) ...
    assert next(r[1] for r in rows if r and r[0] == "Scope disclaimer") == SCOPE_DISCLAIMER
    header = next(r for r in rows if r and r[0] == "Vendor")
    by_name = {r[0]: r for r in rows[rows.index(header) + 1 :] if r}
    # ... and honest data holds: unscored is blank (never 0.0), Not Assessed stays.
    assert by_name["Alpha Unmapped"][header.index("Max CVSS")] == ""
    assert by_name["Alpha Unmapped"][header.index("Tier")] == "Not Assessed"
    assert by_name["Beta Scored"][header.index("Max CVSS")] == "9.1"


def test_export_request_is_audited(api, ex):
    client, oid = _seed(api)
    job_id = _create(client, oid, "csv").json()["id"]
    log = client.get(f"{API}/orgs/{oid}/audit-log").json()
    entry = next(e for e in log if e["action"] == "export.requested")
    assert entry["target_id"] == str(job_id)
    assert entry["extra"] == {"format": "csv"}


def test_list_and_get_jobs_newest_first(api, ex):
    client, oid = _seed(api)
    first = _create(client, oid, "csv").json()["id"]
    second = _create(client, oid, "csv").json()["id"]
    listed = client.get(f"{API}/orgs/{oid}/exports").json()
    assert [j["id"] for j in listed][:2] == [second, first]
    assert client.get(f"{API}/orgs/{oid}/exports/{first}").json()["status"] == "succeeded"


def test_viewer_can_export(api, ex):
    owner, oid = _seed(api)
    viewer, _ = api.register("viewer@acme.io")
    with api.db() as db:
        user = db.query(User).filter_by(email="viewer@acme.io").one()
        db.add(Membership(org_id=oid, user_id=user.id, role=Role.viewer))
        db.commit()
    assert _create(viewer, oid).status_code == 202


# --------------------------------------------------------------------------- #
# Not ready / failed / capped                                                  #
# --------------------------------------------------------------------------- #
def test_queued_job_is_not_downloadable_yet(api, ex):
    ex.mode = "record"  # enqueued, no worker has run it
    client, oid = _seed(api)
    job = _create(client, oid).json()
    assert job["status"] == "queued"
    assert ex.dispatched == [job["id"]]
    redirect, _ = _download(client, oid, job["id"])
    assert redirect.status_code == 409
    assert "being prepared" in redirect.json()["detail"]

    ex.run(job["id"])  # the worker picks it up
    assert _download(client, oid, job["id"])[1].status_code == 200


def test_active_jobs_are_capped_per_org(api, ex, monkeypatch):
    monkeypatch.setenv("EXPORT_MAX_ACTIVE_PER_ORG", "2")
    get_settings.cache_clear()
    ex.mode = "record"
    client, oid = _seed(api)
    assert _create(client, oid).status_code == 202
    assert _create(client, oid).status_code == 202
    res = _create(client, oid)
    assert res.status_code == 429
    # Finishing one frees a slot.
    ex.run(ex.dispatched[0])
    assert _create(client, oid).status_code == 202


def test_broker_down_fails_the_job_and_returns_503(api, ex):
    ex.mode = "fail"
    client, oid = _seed(api)
    res = _create(client, oid)
    assert res.status_code == 503
    assert res.json()["detail"] == export_service.DISPATCH_FAILED
    job = client.get(f"{API}/orgs/{oid}/exports").json()[0]
    assert job["status"] == "failed"
    assert job["error"] == export_service.DISPATCH_FAILED
    assert _download(client, oid, job["id"])[0].status_code == 409


def test_pdf_without_weasyprint_fails_with_a_clear_message(api, ex, monkeypatch):
    def _no_gtk(*_a, **_k):
        raise OSError("cannot load library 'gobject-2.0-0'")

    monkeypatch.setattr(export_service, "portfolio_pdf", _no_gtk)
    client, oid = _seed(api)
    job = _create(client, oid, "pdf").json()
    assert job["status"] == "failed"
    assert job["error"] == export_service.PDF_UNAVAILABLE
    assert ex.files() == []


def test_unexpected_render_error_is_generic_to_the_user(api, ex, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(export_service, "portfolio_csv", _boom)
    client, oid = _seed(api)
    job = _create(client, oid, "csv").json()
    assert job["status"] == "failed"
    assert job["error"] == export_service.RENDER_FAILED
    assert "secret" not in job["error"]


def test_run_job_is_idempotent(api, ex):
    ex.mode = "record"
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]
    assert ex.run(job_id).status is ExportStatus.succeeded
    again = ex.run(job_id)  # a redelivered task (acks_late)
    assert again.status is ExportStatus.succeeded
    assert len(ex.files()) == 1  # rendered and stored exactly once
    assert ex.run(987654) is None  # unknown job: nothing to do


# --------------------------------------------------------------------------- #
# Tenancy                                                                      #
# --------------------------------------------------------------------------- #
def test_other_orgs_cannot_see_or_download_a_job(api, ex):
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]

    outsider, _ = api.register("out@other.io", org_name="Other")
    other_oid = outsider.get(f"{API}/orgs").json()[0]["id"]
    # Not a member of Acme: 404 everywhere (membership is not disclosed).
    assert outsider.get(f"{API}/orgs/{oid}/exports").status_code == 404
    assert outsider.get(f"{API}/orgs/{oid}/exports/{job_id}").status_code == 404
    assert _download(outsider, oid, job_id)[0].status_code == 404
    assert _create(outsider, oid).status_code == 404
    # Addressing Acme's job through their own org doesn't work either.
    assert outsider.get(f"{API}/orgs/{other_oid}/exports/{job_id}").status_code == 404
    assert _download(outsider, other_oid, job_id)[0].status_code == 404
    assert outsider.get(f"{API}/orgs/{other_oid}/exports").json() == []


# --------------------------------------------------------------------------- #
# Retention                                                                    #
# --------------------------------------------------------------------------- #
def _age_job(api, job_id, *, hours):
    with api.db() as db:
        job = db.get(ExportJob, job_id)
        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
        job.expires_at = past
        job.created_at = past
        db.commit()


def test_expired_job_is_gone_then_purged(api, ex):
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]
    assert len(ex.files()) == 1
    _age_job(api, job_id, hours=1)

    # Past retention but not yet purged: reported expired, download refused.
    assert client.get(f"{API}/orgs/{oid}/exports/{job_id}").json()["status"] == "expired"
    assert _download(client, oid, job_id)[0].status_code == 410

    with api.db() as db:
        assert export_service.purge(db, ex.storage) == {"expired": 1, "timed_out": 0}
    assert ex.files() == []
    with api.db() as db:
        job = db.get(ExportJob, job_id)
        assert job.status is ExportStatus.expired and job.object_key is None
    assert _download(client, oid, job_id)[0].status_code == 410


def test_purge_keeps_the_job_when_the_delete_fails(api, ex, monkeypatch):
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]
    _age_job(api, job_id, hours=1)

    def _flaky(key):
        raise ConnectionError("store unreachable")

    monkeypatch.setattr(ex.storage, "delete", _flaky)
    with api.db() as db:
        assert export_service.purge(db, ex.storage)["expired"] == 0
        assert db.get(ExportJob, job_id).object_key  # retried next run
    assert _download(client, oid, job_id)[0].status_code == 410  # still refused


def test_purge_fails_jobs_stuck_by_a_dead_worker(api, ex):
    ex.mode = "record"
    client, oid = _seed(api)
    stuck = _create(client, oid).json()["id"]
    fresh = _create(client, oid).json()["id"]
    _age_job(api, stuck, hours=2)
    with api.db() as db:
        assert export_service.purge(db, ex.storage) == {"expired": 0, "timed_out": 1}
        assert db.get(ExportJob, stuck).error == export_service.TIMED_OUT
        assert db.get(ExportJob, fresh).status is ExportStatus.queued
    # A late delivery of the timed-out job does nothing.
    assert ex.run(stuck).status is ExportStatus.failed
    assert ex.files() == []


# --------------------------------------------------------------------------- #
# Local signed URLs                                                            #
# --------------------------------------------------------------------------- #
def _signed_parts(url):
    parts = urlsplit(url)
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


def test_local_link_rejects_tampering_and_expiry(api, ex):
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]
    location = _download(client, oid, job_id)[0].headers["location"]
    path, q = _signed_parts(location)
    anon = api.client()  # signed links need no session cookie ...
    assert anon.get(location).status_code == 200

    def get(**changes):
        return anon.get(path, params={**q, **changes})

    # ... but every signed field is binding.
    assert get(sig="0" * 64).status_code == 403
    assert get(type="text/html").status_code == 403
    assert get(name="evil.html").status_code == 403
    assert get(exp=str(int(q["exp"]) + 3600)).status_code == 403
    expired = ex.storage.signed_url(
        path.removeprefix(LocalStorage.URL_PREFIX + "/"), filename=q["name"],
        content_type=q["type"], expires_in=60, now=0,
    )
    assert anon.get(expired).status_code == 403


def test_local_link_route_is_off_for_s3(api, ex):
    client, oid = _seed(api)
    job_id = _create(client, oid).json()["id"]
    location = _download(client, oid, job_id)[0].headers["location"]
    api.app.dependency_overrides[get_export_storage] = lambda: _s3()
    assert client.get(location).status_code == 404


def test_local_storage_confines_keys(tmp_path):
    store = LocalStorage(tmp_path, secret="s")
    for bad in ("../x", "a/../../x", "/etc/passwd", "a//b", ".hidden", "a/./b", "a\\b", ""):
        with pytest.raises(ValueError):
            store.path_for(bad)
    store.put("exports/1/ab/f.csv", b"data", content_type="text/csv")
    assert (tmp_path / "exports/1/ab/f.csv").read_bytes() == b"data"
    assert not list(tmp_path.rglob("*.part"))  # written atomically
    store.delete("exports/1/ab/f.csv")
    store.delete("exports/1/ab/f.csv")  # deleting twice is fine
    assert not (tmp_path / "exports/1/ab/f.csv").exists()


def test_content_disposition_is_safe_and_unicode_aware():
    assert content_disposition("report.csv") == (
        "attachment; filename=\"report.csv\"; filename*=UTF-8''report.csv"
    )
    header = content_disposition('bad"name\r\n.csv')
    assert "\r" not in header and "\n" not in header
    assert 'filename="bad_name__.csv"' in header
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in content_disposition("résumé.pdf")
    assert check_key("exports/1/abc/vendor-risk-acme-20260924.csv")


# --------------------------------------------------------------------------- #
# S3 backend (offline)                                                         #
# --------------------------------------------------------------------------- #
def _s3(**kwargs) -> S3Storage:
    return S3Storage(
        bucket="exports-bucket",
        endpoint_url="http://minio:9000",
        public_endpoint_url="http://localhost:9000",
        access_key_id="test-key",
        secret_access_key="test-secret",
        **kwargs,
    )


def test_s3_presigns_against_the_public_endpoint():
    store = _s3()
    url = store.signed_url(
        "exports/1/abc/report.pdf", filename="report.pdf",
        content_type="application/pdf", expires_in=300,
    )
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    # Signed for the host the browser reaches, not the Docker-internal one.
    assert parts.netloc == "localhost:9000"
    assert parts.path == "/exports-bucket/exports/1/abc/report.pdf"  # path-style
    assert q["X-Amz-Expires"] == ["300"]
    assert q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "X-Amz-Signature" in q
    assert q["response-content-disposition"] == [content_disposition("report.pdf")]
    assert q["response-content-type"] == ["application/pdf"]
    assert "test-secret" not in url


def test_build_storage_from_settings(tmp_path):
    local = build_storage(Settings(export_storage="local", export_local_dir=str(tmp_path)))
    assert isinstance(local, LocalStorage) and local.root == tmp_path.resolve()

    # Blank .env lines ("S3_ENDPOINT_URL=") mean unset: plain AWS S3, not "".
    s3 = build_storage(Settings(export_storage="S3", s3_endpoint_url="",
                                s3_public_endpoint_url="", s3_region="eu-west-1"))
    assert isinstance(s3, S3Storage)
    assert "amazonaws.com" in s3.client.meta.endpoint_url
    assert s3.signing_client is s3.client

    with pytest.raises(ValueError):
        build_storage(Settings(export_storage="ftp"))


def test_s3_uses_one_client_when_endpoints_match():
    store = S3Storage(bucket="b", endpoint_url="http://s3.local:9000",
                      access_key_id="k", secret_access_key="s")
    assert store.signing_client is store.client


def test_s3_put_and_delete_hit_the_internal_endpoint():
    store = _s3()
    assert store.client.meta.endpoint_url == "http://minio:9000"
    with Stubber(store.client) as stub:
        stub.add_response(
            "put_object", {},
            {"Bucket": "exports-bucket", "Key": "exports/1/abc/f.csv",
             "Body": b"a,b\n", "ContentType": "text/csv"},
        )
        stub.add_response("delete_object", {}, {"Bucket": "exports-bucket", "Key": "exports/1/abc/f.csv"})
        store.put("exports/1/abc/f.csv", b"a,b\n", content_type="text/csv")
        store.delete("exports/1/abc/f.csv")
        stub.assert_no_pending_responses()


def test_s3_creates_a_missing_bucket_once():
    store = _s3(create_bucket=True)
    with Stubber(store.client) as stub:
        stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
        stub.add_response("create_bucket", {}, {"Bucket": "exports-bucket"})
        stub.add_response("put_object", {})
        stub.add_response("put_object", {})  # second write: no bucket check
        store.put("exports/1/a/f.csv", b"1", content_type="text/csv")
        store.put("exports/1/b/f.csv", b"2", content_type="text/csv")
        stub.assert_no_pending_responses()


def test_s3_bucket_race_is_tolerated():
    store = _s3(create_bucket=True)
    with Stubber(store.client) as stub:
        stub.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
        stub.add_client_error("create_bucket", service_error_code="BucketAlreadyOwnedByYou",
                              http_status_code=409)
        stub.add_response("put_object", {})
        store.put("exports/1/a/f.csv", b"1", content_type="text/csv")
        stub.assert_no_pending_responses()


# --------------------------------------------------------------------------- #
# Real PDF (only where WeasyPrint + GTK exist, i.e. the Docker image)          #
# --------------------------------------------------------------------------- #
def _weasyprint_ok() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _weasyprint_ok(), reason="WeasyPrint/GTK not available")
def test_pdf_export_job_produces_a_pdf(api, ex):
    client, oid = _seed(api)
    job = _create(client, oid, "pdf").json()
    assert job["status"] == "succeeded"
    file = _download(client, oid, job["id"])[1]
    assert file.headers["content-type"] == "application/pdf"
    assert file.content[:5] == b"%PDF-"


def test_every_format_has_a_content_type():
    assert set(export_service.CONTENT_TYPES) == set(ExportFormat)
