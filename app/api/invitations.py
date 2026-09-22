"""Invitation acceptance (not org-scoped by path — the token identifies the org)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas.org import OrgWithRole
from ..services import org_service

router = APIRouter(prefix="/invitations", tags=["orgs"])


class AcceptRequest(BaseModel):
    token: str


@router.post("/accept", response_model=OrgWithRole)
def accept_invitation(
    body: AcceptRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> OrgWithRole:
    membership = org_service.accept_invitation(db, token=body.token, user=user)
    org = membership.organization
    return OrgWithRole(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan,
        created_at=org.created_at, role=membership.role,
    )
