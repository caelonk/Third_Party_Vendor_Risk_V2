"""The signed-in user's profile: display name and recent sign-ins."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    # Blank or null clears the display name.
    name: str | None = Field(default=None, max_length=200)


class LoginEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    method: str  # "password" | "google"
    ip: str | None
    user_agent: str | None
