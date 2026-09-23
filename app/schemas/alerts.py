"""Alert rule and notification DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.base import AlertChannel, AlertType


class AlertRuleCreate(BaseModel):
    type: AlertType
    channel: AlertChannel = AlertChannel.email
    config: dict = Field(default_factory=dict)


class AlertRuleUpdate(BaseModel):
    is_active: bool | None = None
    config: dict | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: AlertType
    channel: AlertChannel
    config: dict
    is_active: bool
    created_at: datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: AlertType
    vendor_id: int | None
    title: str
    body: str | None
    status: str
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int
