"""Vendor DTOs, including the computed risk assessment and sync-run result."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DataSensitivity = Literal["public", "internal", "confidential", "regulated"]
Criticality = Literal["low", "medium", "high"]


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cpe_prefix: str | None = Field(default=None, max_length=255)
    annual_contract_value: float | None = Field(default=None, ge=0)
    data_sensitivity: DataSensitivity | None = None
    business_criticality: Criticality | None = None
    contract_renewal_date: date | None = None


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    cpe_prefix: str | None = Field(default=None, max_length=255)
    annual_contract_value: float | None = Field(default=None, ge=0)
    data_sensitivity: DataSensitivity | None = None
    business_criticality: Criticality | None = None
    contract_renewal_date: date | None = None


class VendorAssessment(BaseModel):
    tier: str
    threat_band: str | None
    exposure_band: str | None
    max_cvss: float | None
    cve_count: int
    kev_count: int


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    cpe_prefix: str | None
    match_method: str | None
    is_mapped: bool
    annual_contract_value: float | None
    data_sensitivity: str | None
    business_criticality: str | None
    contract_renewal_date: date | None
    last_synced_at: datetime | None
    assessment: VendorAssessment


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    vendors_attempted: int | None
    vendors_succeeded: int | None
    cves_upserted: int | None
    error_detail: str | None
    completed_at: datetime | None
