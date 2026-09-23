"""Alert rule management and the in-app notification feed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_org_context, require_role
from ..models import Role
from ..schemas.alerts import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    NotificationOut,
    UnreadCount,
)
from ..services import alerts_service

router = APIRouter(prefix="/orgs/{org_id}", tags=["alerts"])


# --------------------------------------------------------------- Alert rules --
@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_rules(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[AlertRuleOut]:
    return [AlertRuleOut.model_validate(r) for r in alerts_service.list_rules(db, ctx.organization.id)]


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: AlertRuleCreate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> AlertRuleOut:
    rule = alerts_service.create_rule(
        db, ctx.organization.id, type=body.type, channel=body.channel, config=body.config
    )
    return AlertRuleOut.model_validate(rule)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> AlertRuleOut:
    rule = alerts_service.update_rule(
        db, ctx.organization.id, rule_id, is_active=body.is_active, config=body.config
    )
    return AlertRuleOut.model_validate(rule)


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> None:
    alerts_service.delete_rule(db, ctx.organization.id, rule_id)


# ------------------------------------------------------------- Notifications --
@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationOut]:
    return [
        NotificationOut.model_validate(n)
        for n in alerts_service.list_notifications(db, ctx.organization.id, limit=limit)
    ]


@router.get("/notifications/unread-count", response_model=UnreadCount)
def unread_count(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> UnreadCount:
    return UnreadCount(unread=alerts_service.unread_count(db, ctx.organization.id))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> NotificationOut:
    n = alerts_service.mark_read(db, ctx.organization.id, notification_id)
    return NotificationOut.model_validate(n)


@router.post("/notifications/read-all", response_model=UnreadCount)
def mark_all_read(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> UnreadCount:
    alerts_service.mark_all_read(db, ctx.organization.id)
    return UnreadCount(unread=0)
