"""Export job DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..models import ExportFormat, ExportStatus


class ExportCreate(BaseModel):
    format: ExportFormat


class ExportJobOut(BaseModel):
    id: int
    format: ExportFormat
    status: ExportStatus
    filename: str | None
    size_bytes: int | None
    error: str | None
    requested_by: str | None
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
