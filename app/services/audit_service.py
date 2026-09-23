"""Audit log: who did what, for audit-ready reporting.

Entries are recorded at the API layer, where the acting user is known, right
after a mutation succeeds. Secrets are never recorded — an NVD-key change logs
*that* it changed, never the value. Surfaced via GET /orgs/{id}/audit-log
(admin+); see [[export_service]] for the sibling reporting exports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, User


@dataclass
class AuditEntry:
    id: int
    action: str
    target_type: str | None
    target_id: str | None
    actor_user_id: int | None
    actor_email: str | None
    actor_name: str | None
    extra: dict | None
    created_at: datetime


def record(
    db: Session,
    *,
    org_id: int,
    actor_user_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: object = None,
    extra: dict | None = None,
) -> AuditLog:
    """Append one audit entry (its own commit; auditing never rolls back the action)."""
    entry = AuditLog(
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        extra=extra,
    )
    db.add(entry)
    db.commit()
    return entry


def list_entries(db: Session, org_id: int, *, limit: int = 100, offset: int = 0) -> list[AuditEntry]:
    """Newest-first audit entries for an org, with the actor resolved."""
    rows = db.execute(
        select(AuditLog, User.email, User.name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.org_id == org_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        AuditEntry(
            id=log.id,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            actor_user_id=log.actor_user_id,
            actor_email=email,
            actor_name=name,
            extra=log.extra,
            created_at=log.created_at,
        )
        for log, email, name in rows
    ]
