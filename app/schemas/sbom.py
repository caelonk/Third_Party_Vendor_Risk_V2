"""SBOM import DTOs: preview candidates and the import request/result."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SbomCandidate(BaseModel):
    name: str
    cpe_prefix: str | None
    versions: list[str]
    component_count: int
    supplier: str | None
    status: Literal["new", "exists", "duplicate"]


class SbomPreview(BaseModel):
    format: Literal["cyclonedx", "spdx"]
    spec_version: str | None
    subject: str | None
    component_count: int
    candidates: list[SbomCandidate]


class SbomImportItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cpe_prefix: str | None = Field(default=None, max_length=255)


class SbomImportRequest(BaseModel):
    items: list[SbomImportItem] = Field(min_length=1, max_length=500)


class SbomSkipped(BaseModel):
    name: str
    reason: Literal["exists", "invalid_cpe", "empty_name"]


class SbomImportResult(BaseModel):
    created: int
    names: list[str]
    skipped: list[SbomSkipped]
