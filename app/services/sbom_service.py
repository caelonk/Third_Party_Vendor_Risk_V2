"""SBOM import: a read-only preview, then a bulk create of the selected rows.

The flow is stateless — the preview parses the uploaded SBOM and returns
candidates; the client sends back the rows the user kept. Imported vendors start
unmapped-and-unassessed (``is_mapped=False`` -> "Not Assessed"); those with a CPE
prefix are picked up by the next scheduled sync (see scheduled_sync_service).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import sbom

from ..models import Vendor
from .exceptions import ValidationError

MAX_COMPONENTS = 20_000
MAX_IMPORT = 500


def _existing(db: Session, org_id: int) -> tuple[set[str], set[str]]:
    rows = db.execute(select(Vendor.name, Vendor.cpe_prefix).where(Vendor.org_id == org_id)).all()
    # Form-entered prefixes are stored as typed; normalize so casing can't hide a match.
    return {n.casefold() for n, _ in rows}, {sbom.cpe_prefix(p) or p for _, p in rows if p}


def preview(db: Session, org_id: int, doc: object) -> dict:
    """Parse an SBOM into candidates, each marked new / exists / duplicate."""
    try:
        parsed = sbom.parse_sbom(doc)
    except sbom.SbomError as exc:
        raise ValidationError(str(exc)) from exc
    components = parsed["components"]
    if len(components) > MAX_COMPONENTS:
        raise ValidationError(f"SBOM has {len(components)} components; the limit is {MAX_COMPONENTS}.")

    candidates = sbom.build_candidates(components)
    names, prefixes = _existing(db, org_id)
    seen: set[str] = set()
    for c in candidates:
        key = c["name"].casefold()
        if key in names or (c["cpe_prefix"] and c["cpe_prefix"] in prefixes):
            c["status"] = "exists"
        elif key in seen:
            c["status"] = "duplicate"  # same name as an earlier (mapped-first) row
        else:
            c["status"] = "new"
        seen.add(key)

    return {
        "format": parsed["format"],
        "spec_version": parsed["spec_version"],
        "subject": parsed["subject"],
        "component_count": len(components),
        "candidates": candidates,
    }


def import_vendors(db: Session, org_id: int, items: list[dict]) -> dict:
    """Create vendors for the selected rows; skip anything already present."""
    if len(items) > MAX_IMPORT:
        raise ValidationError(f"Import at most {MAX_IMPORT} vendors at a time.")

    names, prefixes = _existing(db, org_id)
    created: list[str] = []
    skipped: list[dict] = []
    for item in items:
        name = (item.get("name") or "").strip()[:200]
        raw_prefix = item.get("cpe_prefix")
        # Re-normalize rather than trusting the client's copy of the prefix.
        prefix = sbom.cpe_prefix(raw_prefix) if raw_prefix else None
        if not name:
            skipped.append({"name": name, "reason": "empty_name"})
        elif raw_prefix and prefix is None:
            skipped.append({"name": name, "reason": "invalid_cpe"})
        elif name.casefold() in names or (prefix and prefix in prefixes):
            skipped.append({"name": name, "reason": "exists"})
        else:
            db.add(Vendor(org_id=org_id, name=name, cpe_prefix=prefix, is_mapped=False))
            created.append(name)
            names.add(name.casefold())
            if prefix:
                prefixes.add(prefix)
    db.commit()
    return {"created": len(created), "names": created, "skipped": skipped}
