"""Name-to-CPE onboarding: CPE-dictionary parsing/grouping + the search service.

No network — the NVD CPE payload is a saved real-shaped fixture, and the service
takes an injected fetch so the live client is never called here.
"""
import json
from pathlib import Path

from core import parser

FIXTURE = Path(__file__).parent / "fixtures" / "cpe_search.json"
API = "/api/v1"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Parser: flatten products, derive prefixes                                   #
# --------------------------------------------------------------------------- #
def test_parse_products_derives_prefix_and_part():
    products = parser.parse_cpe_products(_payload())
    fortios = next(p for p in products if p["product"] == "fortios")
    assert fortios["prefix"] == "cpe:2.3:o:fortinet:fortios"
    assert fortios["part"] == "o"
    assert fortios["vendor"] == "fortinet"


def test_parse_skips_rows_without_a_full_cpe_name():
    # The 4-component "cpe:2.3:a:fortinet" row cannot yield a product prefix.
    products = parser.parse_cpe_products(_payload())
    assert all(len(p["prefix"].split(":")) == 5 for p in products)
    assert not any(p["prefix"] == "cpe:2.3:a:fortinet" for p in products)


# --------------------------------------------------------------------------- #
# Grouping: collapse version rows into distinct products                      #
# --------------------------------------------------------------------------- #
def test_group_collapses_versions_and_counts():
    groups = parser.group_cpe_products(parser.parse_cpe_products(_payload()))
    by_prefix = {g["prefix"]: g for g in groups}
    # 3 distinct products (fortios, fortimanager, forti_manager_cloud).
    assert set(by_prefix) == {
        "cpe:2.3:o:fortinet:fortios",
        "cpe:2.3:a:fortinet:fortimanager",
        "cpe:2.3:a:fortinet:forti_manager_cloud",
    }
    assert by_prefix["cpe:2.3:o:fortinet:fortios"]["version_count"] == 3


def test_group_marks_active_when_any_version_is_not_deprecated():
    groups = parser.group_cpe_products(parser.parse_cpe_products(_payload()))
    fortios = next(g for g in groups if g["prefix"] == "cpe:2.3:o:fortinet:fortios")
    assert fortios["active"] is True  # 2 active + 1 deprecated -> active


def test_group_humanizes_label_and_orders_by_version_count():
    groups = parser.group_cpe_products(parser.parse_cpe_products(_payload()))
    assert groups[0]["prefix"] == "cpe:2.3:o:fortinet:fortios"  # 3 versions -> first
    cloud = next(g for g in groups if g["product"] == "forti_manager_cloud")
    assert cloud["label"] == "Fortinet Forti Manager Cloud"  # underscores -> spaces


# --------------------------------------------------------------------------- #
# Service: search_products orchestration (injected fetch)                     #
# --------------------------------------------------------------------------- #
def test_search_products_service_returns_grouped_candidates():
    from app.services import cpe_service

    calls = []

    def fake_fetch(keyword: str) -> dict:
        calls.append(keyword)
        return _payload()

    candidates = cpe_service.search_products("fortinet", fetch_cpes=fake_fetch)
    assert calls == ["fortinet"]
    assert [c["prefix"] for c in candidates][:1] == ["cpe:2.3:o:fortinet:fortios"]
    assert len(candidates) == 3


def test_search_products_blank_keyword_skips_fetch():
    from app.services import cpe_service

    def boom(_keyword: str) -> dict:  # pragma: no cover - must not be called
        raise AssertionError("fetch should be skipped for a blank keyword")

    assert cpe_service.search_products("  ", fetch_cpes=boom) == []


# --------------------------------------------------------------------------- #
# API: GET /orgs/{id}/cpe-search                                              #
# --------------------------------------------------------------------------- #
def _org_id(client) -> int:
    return client.get(f"{API}/orgs").json()[0]["id"]


def _override_fetch(api, fetch):
    from app.api import cpe as cpe_api

    api.app.dependency_overrides[cpe_api.get_cpe_fetcher] = lambda: fetch


def test_cpe_search_endpoint_returns_candidates(api):
    client, _ = api.register("cpe@acme.io")
    oid = _org_id(client)
    _override_fetch(api, lambda _kw: _payload())

    res = client.get(f"{API}/orgs/{oid}/cpe-search", params={"q": "fortinet"})
    assert res.status_code == 200
    body = res.json()
    assert body[0]["prefix"] == "cpe:2.3:o:fortinet:fortios"
    assert body[0]["version_count"] == 3
    assert body[0]["active"] is True


def test_cpe_search_short_query_returns_empty_without_fetch(api):
    client, _ = api.register("cpe2@acme.io")
    oid = _org_id(client)

    def boom(_kw):  # pragma: no cover - must not be called
        raise AssertionError("fetch should not run for a short query")

    _override_fetch(api, boom)
    res = client.get(f"{API}/orgs/{oid}/cpe-search", params={"q": "f"})
    assert res.status_code == 200 and res.json() == []


def test_cpe_search_non_member_gets_404(api):
    owner, _ = api.register("cpe-o@acme.io")
    oid = _org_id(owner)
    outsider, _ = api.register("cpe-out@acme.io")
    _override_fetch(api, lambda _kw: _payload())
    res = outsider.get(f"{API}/orgs/{oid}/cpe-search", params={"q": "fortinet"})
    assert res.status_code == 404
