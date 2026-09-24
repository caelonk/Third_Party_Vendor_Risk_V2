"""Org-scoped vendor CRUD + on-demand sync."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from core.sync import FetchFn

from ..db import get_session
from ..deps import OrgContext, get_org_context, require_role
from ..models import Role, Vendor
from ..schemas.vendor import (
    SyncRunOut,
    VendorAssessment,
    VendorCreate,
    VendorOut,
    VendorUpdate,
)
from ..services import audit_service, scoring_service, sync_service, vendor_service

router = APIRouter(prefix="/orgs/{org_id}/vendors", tags=["vendors"])

_ASSESSMENT_KEYS = ("tier", "threat_band", "exposure_band", "max_cvss", "cve_count", "kev_count")


def get_vendor_fetcher(
    org_id: int = Path(...),
    db: Session = Depends(get_session),
) -> FetchFn:
    """Live NVD fetcher for the Sync button: the org's key, shared rate limit.
    Overridden in tests to replay saved fixtures."""
    return sync_service.live_fetch_for_org(db, org_id)


def _vendor_out(db: Session, vendor: Vendor, assessment: dict | None = None) -> VendorOut:
    a = assessment if assessment is not None else scoring_service.assess_vendor(db, vendor)
    return VendorOut(
        id=vendor.id,
        name=vendor.name,
        cpe_prefix=vendor.cpe_prefix,
        match_method=vendor.match_method.value if vendor.match_method else None,
        is_mapped=vendor.is_mapped,
        annual_contract_value=vendor.annual_contract_value,
        data_sensitivity=vendor.data_sensitivity,
        business_criticality=vendor.business_criticality,
        contract_renewal_date=vendor.contract_renewal_date,
        last_synced_at=vendor.last_synced_at,
        assessment=VendorAssessment(**{k: a[k] for k in _ASSESSMENT_KEYS}),
    )


@router.get("", response_model=list[VendorOut])
def list_vendors(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[VendorOut]:
    vendors = vendor_service.list_vendors(db, ctx.organization.id)
    assessments = scoring_service.assess_vendors(db, vendors)  # one batched CVE query
    return [_vendor_out(db, v, assessments[v.id]) for v in vendors]


@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(
    body: VendorCreate,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> VendorOut:
    vendor = vendor_service.create_vendor(db, ctx.organization.id, body.model_dump())
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="vendor.created", target_type="vendor", target_id=vendor.id,
        extra={"name": vendor.name},
    )
    return _vendor_out(db, vendor)


@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(
    vendor_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> VendorOut:
    vendor = vendor_service.get_vendor(db, ctx.organization.id, vendor_id)
    return _vendor_out(db, vendor)


@router.patch("/{vendor_id}", response_model=VendorOut)
def update_vendor(
    vendor_id: int,
    body: VendorUpdate,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> VendorOut:
    vendor = vendor_service.update_vendor(
        db, ctx.organization.id, vendor_id, body.model_dump(exclude_unset=True)
    )
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="vendor.updated", target_type="vendor", target_id=vendor.id,
        extra={"fields": sorted(body.model_dump(exclude_unset=True).keys())},
    )
    return _vendor_out(db, vendor)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor(
    vendor_id: int,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> None:
    vendor = vendor_service.get_vendor(db, ctx.organization.id, vendor_id)
    name = vendor.name
    vendor_service.delete_vendor(db, ctx.organization.id, vendor_id)
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="vendor.deleted", target_type="vendor", target_id=vendor_id,
        extra={"name": name},
    )


@router.post("/{vendor_id}/sync", response_model=SyncRunOut)
def sync_vendor(
    vendor_id: int,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
    fetch: FetchFn = Depends(get_vendor_fetcher),
) -> SyncRunOut:
    vendor = vendor_service.get_vendor(db, ctx.organization.id, vendor_id)
    run = sync_service.sync_vendor(db, ctx.organization.id, vendor, fetch=fetch)
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="vendor.synced", target_type="vendor", target_id=vendor.id,
        extra={"status": run.status.value, "cves_upserted": run.cves_upserted},
    )
    return SyncRunOut.model_validate(run)
