"""SBOM parsing: CycloneDX JSON and SPDX 2.x JSON -> vendor-import candidates.

An SBOM lists the software components inside one product (its *subject*). Each
dependency is a candidate vendor. Components that carry a CPE collapse to one
product-level prefix (``cpe:2.3:<part>:<vendor>:<product>``) — the same form the
CPE-dictionary search derives and CVE sync uses as a ``virtualMatchString`` — so
``log4j-core`` and ``log4j-api`` become one "Apache Log4j" vendor. Components
without a usable CPE become unmapped candidates keyed by name.

Scoring is product-level across all published versions; SBOM versions are kept
for display only and do not narrow CVE matching.

Pure and dependency-free (stdlib only), like the rest of ``core``.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

from .parser import humanize_product


class SbomError(ValueError):
    """The document is not a CycloneDX or SPDX 2.x JSON SBOM we can read."""


_UNESCAPED_COLON = re.compile(r"(?<!\\):")
_VALID_PARTS = {"a", "o", "h"}  # application, operating system, hardware
_ANY_VALUE = {"", "*", "-"}  # CPE ANY / NA: not a specific product
_NEEDS_ESCAPE = re.compile(r"([^A-Za-z0-9._\-])")


# --------------------------------------------------------------------------- #
# CPE normalization                                                           #
# --------------------------------------------------------------------------- #
def _cpe_fields(cpe: object) -> tuple[str, str, str] | None:
    """(part, vendor, product) from a CPE 2.3 formatted string or a 2.2 URI."""
    if not isinstance(cpe, str):
        return None
    cpe = cpe.strip()
    lowered = cpe.lower()
    if lowered.startswith("cpe:2.3:"):
        fields = _UNESCAPED_COLON.split(cpe)
        if len(fields) < 5:
            return None
        part, vendor, product = fields[2], fields[3], fields[4]
    elif lowered.startswith("cpe:/"):
        fields = cpe[5:].split(":")
        if len(fields) < 3:
            return None
        # 2.2 URIs percent-encode; 2.3 formatted strings backslash-escape.
        part = fields[0]
        vendor = _NEEDS_ESCAPE.sub(r"\\\1", unquote(fields[1]))
        product = _NEEDS_ESCAPE.sub(r"\\\1", unquote(fields[2]))
    else:
        return None
    part = part.lower()
    if part not in _VALID_PARTS or vendor in _ANY_VALUE or product in _ANY_VALUE:
        return None
    return part, vendor.lower(), product.lower()


def cpe_prefix(cpe: object) -> str | None:
    """The product-level CVE-sync prefix for a CPE, or None if it names no product."""
    fields = _cpe_fields(cpe)
    return None if fields is None else "cpe:2.3:{}:{}:{}".format(*fields)


# --------------------------------------------------------------------------- #
# Format parsers -> flat components                                           #
# --------------------------------------------------------------------------- #
def _text(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _component(name, version, cpe, purl, supplier) -> dict:
    return {
        "name": name,
        "version": _text(version),
        "cpe": _text(cpe),
        "purl": _text(purl),
        "supplier": _text(supplier),
    }


def _parse_cyclonedx(doc: dict) -> dict:
    subject = (doc.get("metadata") or {}).get("component") or {}
    subject_ref = subject.get("bom-ref")
    out: list[dict] = []

    def walk(items: object) -> None:
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict):
                continue
            if c.get("type") != "file" and not (subject_ref and c.get("bom-ref") == subject_ref):
                name = _text(c.get("name"))
                group = _text(c.get("group"))
                if name and group and group.startswith("@"):
                    name = f"{group}/{name}"  # npm scope is part of the package name
                if name:
                    supplier = (c.get("supplier") or {}).get("name") if isinstance(
                        c.get("supplier"), dict
                    ) else None
                    out.append(
                        _component(
                            name,
                            c.get("version"),
                            c.get("cpe"),
                            c.get("purl"),
                            supplier or c.get("publisher") or c.get("author"),
                        )
                    )
            walk(c.get("components"))

    walk(doc.get("components"))
    return {
        "format": "cyclonedx",
        "spec_version": _text(doc.get("specVersion")),
        "subject": _text(subject.get("name")),
        "components": out,
    }


def _spdx_supplier(value: object) -> str | None:
    text = _text(value)
    if not text or text.upper() == "NOASSERTION":
        return None
    for prefix in ("Organization:", "Person:", "Tool:"):
        if text.startswith(prefix):
            return _text(text[len(prefix):])
    return text


def _parse_spdx(doc: dict) -> dict:
    doc_id = doc.get("SPDXID", "SPDXRef-DOCUMENT")
    roots = set(doc.get("documentDescribes") or [])
    for rel in doc.get("relationships") or []:
        kind = rel.get("relationshipType")
        if kind == "DESCRIBES" and rel.get("spdxElementId") == doc_id:
            roots.add(rel.get("relatedSpdxElement"))
        elif kind == "DESCRIBED_BY" and rel.get("relatedSpdxElement") == doc_id:
            roots.add(rel.get("spdxElementId"))

    subject: str | None = None
    out: list[dict] = []
    for p in doc.get("packages") or []:
        if not isinstance(p, dict):
            continue
        name = _text(p.get("name"))
        if p.get("SPDXID") in roots:
            subject = subject or name
            continue
        if not name:
            continue
        cpe = purl = None
        for ref in p.get("externalRefs") or []:
            kind = ref.get("referenceType")
            if kind in ("cpe23Type", "cpe22Type") and cpe is None:
                cpe = ref.get("referenceLocator")
            elif kind == "purl" and purl is None:
                purl = ref.get("referenceLocator")
        out.append(_component(name, p.get("versionInfo"), cpe, purl, _spdx_supplier(p.get("supplier"))))

    version = _text(doc.get("spdxVersion"))
    return {
        "format": "spdx",
        "spec_version": version.removeprefix("SPDX-") if version else None,
        "subject": subject,
        "components": out,
    }


def parse_sbom(doc: object) -> dict:
    """Detect the format and flatten the SBOM's dependencies.

    Returns ``{"format", "spec_version", "subject", "components": [...]}`` where
    each component is ``{name, version, cpe, purl, supplier}``.
    """
    if not isinstance(doc, dict):
        raise SbomError("Expected a JSON object: a CycloneDX or SPDX JSON SBOM.")
    if doc.get("bomFormat") == "CycloneDX":
        return _parse_cyclonedx(doc)
    if "spdxVersion" in doc:
        return _parse_spdx(doc)
    if "@context" in doc and "spdx" in str(doc.get("@context")).lower():
        raise SbomError("SPDX 3.0 (JSON-LD) is not supported yet — export SPDX 2.3 JSON instead.")
    raise SbomError("Unrecognized SBOM: expected CycloneDX or SPDX JSON.")


# --------------------------------------------------------------------------- #
# Components -> import candidates                                             #
# --------------------------------------------------------------------------- #
def build_candidates(components: list[dict]) -> list[dict]:
    """Group components into candidates: by CPE product when present, else by name.

    Each candidate is ``{name, cpe_prefix, versions, component_count, supplier}``.
    Mapped candidates come first, then alphabetical.
    """
    groups: dict[tuple[str, str], dict] = {}
    for c in components:
        fields = _cpe_fields(c.get("cpe"))
        prefix: str | None
        if fields:
            product_prefix = "cpe:2.3:{}:{}:{}".format(*fields)
            key = ("cpe", product_prefix)
            prefix = product_prefix
            label = humanize_product(fields[1], fields[2])
        else:
            key = ("name", c["name"].casefold())
            prefix = None
            label = c["name"]
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "name": label[:200],
                "cpe_prefix": prefix,
                "versions": [],
                "component_count": 0,
                "supplier": None,
            }
        g["component_count"] += 1
        version = c.get("version")
        if version and version not in g["versions"]:
            g["versions"].append(version)
        if g["supplier"] is None and c.get("supplier"):
            g["supplier"] = c["supplier"]
    return sorted(groups.values(), key=lambda g: (g["cpe_prefix"] is None, g["name"].casefold()))
