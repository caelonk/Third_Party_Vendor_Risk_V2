"""Per-org integration settings: scheduled-sync cadence and the NVD API key.

The NVD key is write-only (see :mod:`app.schemas.integration`). Reads are open to
any member (cadence + whether a key is set); writes require admin, since the key
is a tenant secret.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session
from ..deps import OrgContext, get_org_context, require_role
from ..models import Role
from ..schemas.integration import IntegrationOut, IntegrationUpdate
from ..services import audit_service, integration_service

router = APIRouter(prefix="/orgs/{org_id}/integration", tags=["integration"])


def _out(integ, *, default_cadence: int) -> IntegrationOut:
    if integ is None:
        return IntegrationOut(nvd_key_set=False, sync_cadence_hours=default_cadence)
    return IntegrationOut(
        nvd_key_set=bool(integ.nvd_api_key_ct),
        sync_cadence_hours=integ.sync_cadence_hours,
    )


@router.get("", response_model=IntegrationOut)
def get_integration(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> IntegrationOut:
    integ = integration_service.get_integration(db, ctx.organization.id)
    return _out(integ, default_cadence=get_settings().default_sync_cadence_hours)


@router.put("", response_model=IntegrationOut)
def update_integration(
    body: IntegrationUpdate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> IntegrationOut:
    patch = body.model_dump(exclude_unset=True)
    integ = integration_service.apply_patch(db, ctx.organization.id, patch)
    # Record that fields changed — never the NVD key value itself.
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="integration.updated", target_type="integration", target_id=ctx.organization.id,
        extra={"fields": sorted(patch.keys())},
    )
    return _out(integ, default_cadence=get_settings().default_sync_cadence_hours)
