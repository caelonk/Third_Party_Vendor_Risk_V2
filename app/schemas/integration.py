"""Schemas for per-org integration settings (auto-sync + NVD key).

The NVD key is write-only: it is accepted on update, encrypted at rest, and never
returned. Reads expose only whether a key is configured and the sync cadence.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IntegrationOut(BaseModel):
    nvd_key_set: bool
    # When NVD last accepted the stored key. Null while a key is set means it was
    # saved without confirmation (NVD could not be reached at the time).
    nvd_key_verified_at: datetime | None = None
    sync_cadence_hours: int
    # The most frequent auto-sync the org's plan allows; a stored cadence below
    # it (e.g. after a downgrade) is raised to it when syncs are scheduled.
    min_sync_hours: int


class IntegrationUpdate(BaseModel):
    # Absent -> unchanged; null or "" -> clear the stored key; else store encrypted.
    nvd_api_key: str | None = Field(default=None, max_length=200)
    sync_cadence_hours: int | None = Field(default=None, ge=1, le=720)
