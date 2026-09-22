"""Dashboard widget DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class SummaryOut(BaseModel):
    vendor_count: int
    mapped_count: int
    tier_distribution: dict[str, int]
    kev_exposed_vendors: int
    total_cves: int


class HeatmapCell(BaseModel):
    threat_band: str
    exposure_band: str
    tier: str
    count: int
    vendors: list[str]


class HeatmapOut(BaseModel):
    cells: list[HeatmapCell]


class WatchlistItem(BaseModel):
    vendor_id: int
    vendor_name: str
    tier: str
    contract_renewal_date: str
    days_until_renewal: int
    max_cvss: float | None
    kev_count: int


class TopRiskItem(BaseModel):
    vendor_id: int
    vendor_name: str
    tier: str
    max_cvss: float | None
    cve_count: int
    kev_count: int
