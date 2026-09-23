"""Audit log viewer (admin+): who did what, newest first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, require_role
from ..models import Role
from ..schemas.audit import AuditEntryOut
from ..services import audit_service

router = APIRouter(prefix="/orgs/{org_id}/audit-log", tags=["audit"])


@router.get("", response_model=list[AuditEntryOut])
def list_audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> list[AuditEntryOut]:
    entries = audit_service.list_entries(db, ctx.organization.id, limit=limit, offset=offset)
    return [
        AuditEntryOut(
            id=e.id,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            actor_email=e.actor_email,
            actor_name=e.actor_name,
            extra=e.extra,
            created_at=e.created_at,
        )
        for e in entries
    ]
