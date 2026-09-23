"""Name-to-CPE onboarding: search the NVD CPE dictionary for a vendor name.

Kept off the ``/vendors/{vendor_id}`` path so the literal segment never collides
with the integer vendor-id route.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context
from ..schemas.vendor import CpeCandidate
from ..services import cpe_service
from ..services.cpe_service import FetchCpesFn

router = APIRouter(prefix="/orgs/{org_id}", tags=["onboarding"])


def get_cpe_fetcher(
    org_id: int = Path(...),
    db: Session = Depends(get_session),
) -> FetchCpesFn:
    """Live NVD CPE fetcher (overridden in tests to replay a fixture)."""
    return cpe_service.build_live_cpe_fetch(db, org_id)


@router.get("/cpe-search", response_model=list[CpeCandidate])
def cpe_search(
    q: str = Query(default="", max_length=100),
    ctx: OrgContext = Depends(get_org_context),
    fetch: FetchCpesFn = Depends(get_cpe_fetcher),
) -> list[CpeCandidate]:
    return [CpeCandidate(**c) for c in cpe_service.search_products(q, fetch_cpes=fetch)]
