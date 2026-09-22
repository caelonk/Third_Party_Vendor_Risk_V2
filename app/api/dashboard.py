"""Org dashboard aggregation endpoints (widget data). Read access for members."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context
from ..schemas.dashboard import HeatmapOut, SummaryOut, TopRiskItem, WatchlistItem
from ..services import dashboard_service

router = APIRouter(prefix="/orgs/{org_id}/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=SummaryOut)
def summary(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> SummaryOut:
    return SummaryOut(**dashboard_service.summary(db, ctx.organization.id))


@router.get("/heatmap", response_model=HeatmapOut)
def heatmap(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> HeatmapOut:
    return HeatmapOut(**dashboard_service.heatmap(db, ctx.organization.id))


@router.get("/watchlist", response_model=list[WatchlistItem])
def watchlist(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[WatchlistItem]:
    return [WatchlistItem(**r) for r in dashboard_service.watchlist(db, ctx.organization.id)]


@router.get("/top-risk", response_model=list[TopRiskItem])
def top_risk(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    limit: int = Query(default=5, ge=1, le=50),
) -> list[TopRiskItem]:
    return [
        TopRiskItem(**r) for r in dashboard_service.top_risk(db, ctx.organization.id, limit=limit)
    ]
