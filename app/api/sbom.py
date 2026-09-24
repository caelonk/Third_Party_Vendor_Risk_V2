"""SBOM import: preview a CycloneDX/SPDX JSON document, then import selected rows.

The SBOM is sent as the JSON request body (no multipart dependency needed; both
supported formats are JSON). Writers only (member+), matching vendor creation.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, require_role
from ..models import Role
from ..schemas.sbom import SbomImportRequest, SbomImportResult, SbomPreview
from ..services import audit_service, sbom_service

router = APIRouter(prefix="/orgs/{org_id}/sbom", tags=["onboarding"])

MAX_SBOM_BYTES = 10 * 1024 * 1024


def _limit_size(content_length: int | None = Header(default=None)) -> None:
    # A coarse guard; hard request-size limits belong at the reverse proxy.
    if content_length is not None and content_length > MAX_SBOM_BYTES:
        # Literal 413: Starlette renamed the constant (…_CONTENT_TOO_LARGE) and
        # deprecated the old one; the number works on every version.
        raise HTTPException(413, f"SBOM is larger than {MAX_SBOM_BYTES // (1024 * 1024)} MB.")


@router.post("/preview", response_model=SbomPreview, dependencies=[Depends(_limit_size)])
def preview_sbom(
    doc: dict[str, Any] = Body(...),
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> SbomPreview:
    return SbomPreview(**sbom_service.preview(db, ctx.organization.id, doc))


@router.post("/import", response_model=SbomImportResult)
def import_sbom(
    body: SbomImportRequest,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> SbomImportResult:
    result = sbom_service.import_vendors(
        db, ctx.organization.id, [item.model_dump() for item in body.items]
    )
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="vendor.imported", target_type="org", target_id=ctx.organization.id,
        extra={"source": "sbom", "created": result["created"], "skipped": len(result["skipped"])},
    )
    return SbomImportResult(**result)
