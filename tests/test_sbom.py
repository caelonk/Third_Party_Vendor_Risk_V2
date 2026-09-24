"""SBOM parsing (CycloneDX JSON, SPDX JSON) into vendor-import candidates.

Pure-core tests against realistic fixtures; no DB or network.
"""
import copy
import json
from pathlib import Path

import pytest

from core import sbom

FIXTURES = Path(__file__).parent / "fixtures" / "sbom"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# CPE normalization                                                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("cpe", "expected"),
    [
        ("cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*", "cpe:2.3:a:apache:log4j"),
        ("cpe:2.3:A:Apache:Log4j:2.14.1:*:*:*:*:*:*:*", "cpe:2.3:a:apache:log4j"),
        ("cpe:/a:openssl:openssl:3.0.7", "cpe:2.3:a:openssl:openssl"),  # CPE 2.2 URI
        ("cpe:/o:linux:linux_kernel", "cpe:2.3:o:linux:linux_kernel"),
        ("cpe:2.3:a:foo\\:bar:baz:1.0:*:*:*:*:*:*:*", "cpe:2.3:a:foo\\:bar:baz"),  # escaped colon
        ("cpe:/a:foo%21:bar", "cpe:2.3:a:foo\\!:bar"),  # 2.2 percent-encoding -> 2.3 escape
        ("cpe:2.3:a:*:*:*:*:*:*:*:*:*:*", None),  # wildcard vendor/product: not a product
        ("cpe:2.3:a:apache:-:*:*:*:*:*:*:*:*", None),
        ("cpe:2.3:x:foo:bar:1:*:*:*:*:*:*:*", None),  # invalid part
        ("cpe:2.3:a:apache", None),  # too short
        ("pkg:npm/lodash@4.17.21", None),
        ("", None),
        (None, None),
    ],
)
def test_cpe_prefix(cpe, expected):
    assert sbom.cpe_prefix(cpe) == expected


# --------------------------------------------------------------------------- #
# CycloneDX                                                                   #
# --------------------------------------------------------------------------- #
def test_cyclonedx_parses_components_and_excludes_subject_and_files():
    parsed = sbom.parse_sbom(_load("cyclonedx.json"))
    assert parsed["format"] == "cyclonedx"
    assert parsed["spec_version"] == "1.5"
    assert parsed["subject"] == "acme-portal"
    names = [c["name"] for c in parsed["components"]]
    assert "acme-portal" not in names  # the SBOM's own subject is not a dependency
    assert "LICENSE.txt" not in names  # file entries are not software
    assert "spring-jcl" in names  # nested components are walked
    assert "@angular/core" in names  # npm scope kept
    assert len(names) == 9


def test_cyclonedx_candidates_collapse_versions_to_products():
    cands = sbom.build_candidates(sbom.parse_sbom(_load("cyclonedx.json"))["components"])
    by_name = {c["name"]: c for c in cands}

    log4j = by_name["Apache Log4j"]
    assert log4j["cpe_prefix"] == "cpe:2.3:a:apache:log4j"
    assert log4j["component_count"] == 2  # log4j-core + log4j-api -> one product
    assert log4j["versions"] == ["2.14.1"]
    assert log4j["supplier"] == "The Apache Software Foundation"

    assert by_name["Openssl"]["cpe_prefix"] == "cpe:2.3:a:openssl:openssl"  # vendor == product

    lodash = by_name["lodash"]
    assert lodash["cpe_prefix"] is None
    assert lodash["versions"] == ["4.17.20", "4.17.21"]
    assert lodash["supplier"] == "OpenJS Foundation"

    assert by_name["weird-lib"]["cpe_prefix"] is None  # wildcard CPE falls back to unmapped


def test_candidates_list_mapped_first_then_by_name():
    cands = sbom.build_candidates(sbom.parse_sbom(_load("cyclonedx.json"))["components"])
    assert [c["name"] for c in cands] == [
        "Apache Log4j",
        "Openssl",
        "Vmware Spring Framework",
        "@angular/core",
        "lodash",
        "spring-jcl",
        "weird-lib",
    ]


# --------------------------------------------------------------------------- #
# SPDX                                                                        #
# --------------------------------------------------------------------------- #
def test_spdx_parses_packages_refs_and_suppliers():
    parsed = sbom.parse_sbom(_load("spdx.json"))
    assert parsed["format"] == "spdx"
    assert parsed["spec_version"] == "2.3"
    assert parsed["subject"] == "acme-portal"

    comps = {c["name"]: c for c in parsed["components"]}
    assert set(comps) == {"nginx", "zlib", "requests"}  # described root excluded
    assert comps["nginx"]["cpe"] == "cpe:2.3:a:f5:nginx:1.24.0:*:*:*:*:*:*:*"
    assert comps["nginx"]["supplier"] == "F5, Inc."  # "Organization: " stripped
    assert comps["zlib"]["cpe"] == "cpe:/a:zlib:zlib:1.2.13"  # cpe22Type ref
    assert comps["zlib"]["supplier"] is None  # NOASSERTION is not a supplier
    assert comps["requests"]["purl"] == "pkg:pypi/requests@2.31.0"
    assert comps["requests"]["supplier"] == "Kenneth Reitz"


def test_spdx_candidates():
    cands = sbom.build_candidates(sbom.parse_sbom(_load("spdx.json"))["components"])
    assert [(c["name"], c["cpe_prefix"]) for c in cands] == [
        ("F5 Nginx", "cpe:2.3:a:f5:nginx"),
        ("Zlib", "cpe:2.3:a:zlib:zlib"),
        ("requests", None),
    ]


def test_spdx_subject_found_via_describes_relationship_alone():
    doc = _load("spdx.json")
    del doc["documentDescribes"]  # deprecated field; rely on the DESCRIBES relationship
    names = {c["name"] for c in sbom.parse_sbom(doc)["components"]}
    assert "acme-portal" not in names


# --------------------------------------------------------------------------- #
# Rejections                                                                  #
# --------------------------------------------------------------------------- #
def test_unrecognized_document_is_rejected():
    with pytest.raises(sbom.SbomError, match="CycloneDX or SPDX"):
        sbom.parse_sbom({"hello": "world"})


def test_spdx_3_json_ld_gets_a_specific_message():
    with pytest.raises(sbom.SbomError, match="SPDX 2"):
        sbom.parse_sbom({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []})


def test_mutation_free():
    doc = _load("cyclonedx.json")
    before = copy.deepcopy(doc)
    sbom.build_candidates(sbom.parse_sbom(doc)["components"])
    assert doc == before
