"""Risk-trend endpoints (read access for members)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context
from ..schemas.trends import PortfolioTrendPoint, VendorTrendPoint
from ..services import snapshot_service, vendor_service

router = APIRouter(prefix="/orgs/{org_id}", tags=["trends"])


@router.get("/snapshots", response_model=list[PortfolioTrendPoint])
def portfolio_trend(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    days: int = Query(default=90, ge=1, le=365),
) -> list[PortfolioTrendPoint]:
    return [
        PortfolioTrendPoint(**p)
        for p in snapshot_service.portfolio_trend(db, ctx.organization.id, days=days)
    ]


@router.get("/vendors/{vendor_id}/trend", response_model=list[VendorTrendPoint])
def vendor_trend(
    vendor_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[VendorTrendPoint]:
    vendor_service.get_vendor(db, ctx.organization.id, vendor_id)  # 404 if not in org
    return [
        VendorTrendPoint(**p)
        for p in snapshot_service.vendor_trend(db, ctx.organization.id, vendor_id)
    ]
