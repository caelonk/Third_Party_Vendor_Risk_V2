"""Audit log DTO."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEntryOut(BaseModel):
    id: int
    action: str
    target_type: str | None
    target_id: str | None
    actor_email: str | None
    actor_name: str | None
    extra: dict | None
    created_at: datetime
