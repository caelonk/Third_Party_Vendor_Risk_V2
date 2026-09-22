"""Org-scoped vendor CRUD + on-demand sync."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
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
from ..services import scoring_service, sync_service, vendor_service

router = APIRouter(prefix="/orgs/{org_id}/vendors", tags=["vendors"])

_ASSESSMENT_KEYS = ("tier", "threat_band", "exposure_band", "max_cvss", "cve_count", "kev_count")


def _vendor_out(db: Session, vendor: Vendor) -> VendorOut:
    a = scoring_service.assess_vendor(db, vendor)
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
    return [_vendor_out(db, v) for v in vendor_service.list_vendors(db, ctx.organization.id)]


@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(
    body: VendorCreate,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> VendorOut:
    vendor = vendor_service.create_vendor(db, ctx.organization.id, body.model_dump())
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
    return _vendor_out(db, vendor)


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor(
    vendor_id: int,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
) -> None:
    vendor_service.delete_vendor(db, ctx.organization.id, vendor_id)


@router.post("/{vendor_id}/sync", response_model=SyncRunOut)
def sync_vendor(
    vendor_id: int,
    ctx: OrgContext = Depends(require_role(Role.member)),
    db: Session = Depends(get_session),
    fetch: FetchFn = Depends(sync_service.get_vendor_fetcher),
) -> SyncRunOut:
    vendor = vendor_service.get_vendor(db, ctx.organization.id, vendor_id)
    run = sync_service.sync_vendor(db, ctx.organization.id, vendor, fetch=fetch)
    return SyncRunOut.model_validate(run)
