"""Schemas for per-org integration settings (auto-sync + NVD key).

The NVD key is write-only: it is accepted on update, encrypted at rest, and never
returned. Reads expose only whether a key is configured and the sync cadence.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class IntegrationOut(BaseModel):
    nvd_key_set: bool
    sync_cadence_hours: int


class IntegrationUpdate(BaseModel):
    # Absent -> unchanged; null or "" -> clear the stored key; else store encrypted.
    nvd_api_key: str | None = Field(default=None)
    sync_cadence_hours: int | None = Field(default=None, ge=1, le=720)
