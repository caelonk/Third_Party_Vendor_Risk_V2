"""Trend DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class VendorTrendPoint(BaseModel):
    captured_at: str
    tier: str
    max_cvss: float | None
    cve_count: int
    kev_count: int


class PortfolioTrendPoint(BaseModel):
    date: str
    total_cves: int
    kev_vendors: int
    tier_distribution: dict[str, int]
