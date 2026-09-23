"""Portfolio exports: CSV (data) and PDF (formatted report).

Any member may export (read-only reporting). Every export carries the scope
disclaimer verbatim; see :mod:`app.services.export_service`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context
from ..services import export_service

router = APIRouter(prefix="/orgs/{org_id}/export", tags=["export"])


@router.get("/vendors.csv")
def export_vendors_csv(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> Response:
    org = ctx.organization
    body = export_service.portfolio_csv(db, org.id, org)
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{export_service.filename(org, "csv")}"'
        },
    )


@router.get("/portfolio.pdf")
def export_portfolio_pdf(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> Response:
    org = ctx.organization
    try:
        pdf = export_service.portfolio_pdf(db, org.id, org)
    except Exception as exc:  # WeasyPrint/GTK missing on this host, or a render error
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF rendering is not available on this server.",
        ) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{export_service.filename(org, "pdf")}"'
        },
    )
