"""User preference DTOs: theme + the customizable dashboard layout."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models.base import Theme
from ..models.user import MAX_DASHBOARD_WIDGETS


class DashboardWidget(BaseModel):
    """One widget on the personal home board."""

    type: str = Field(max_length=64)
    config: dict = Field(default_factory=dict)
    # Compact header vs detailed view; grid geometry for react-grid-layout/dnd-kit.
    expanded: bool = False
    w: int = Field(default=1, ge=1)
    h: int = Field(default=1, ge=1)


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    theme: Theme
    dashboard_layout: list[DashboardWidget]


class PreferencesUpdate(BaseModel):
    theme: Theme | None = None
    # Enforced here AND in the service layer: at most MAX_DASHBOARD_WIDGETS.
    dashboard_layout: list[DashboardWidget] | None = Field(
        default=None, max_length=MAX_DASHBOARD_WIDGETS
    )
