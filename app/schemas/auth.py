"""Auth and user DTOs."""
from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=200)
    # Optional name for the personal org created on registration.
    org_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthProviderOut(BaseModel):
    id: str
    name: str
    dev_stand_in: bool  # the built-in development stand-in, not the real provider


def avatar_version(avatar_key: str | None) -> str | None:
    """A short token that changes whenever the photo does, for cache-busting URLs.
    Derived from the storage key so the key itself never leaves the server."""
    if not avatar_key:
        return None
    return hashlib.sha256(avatar_key.encode()).hexdigest()[:12]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str | None
    is_active: bool
    last_login_at: datetime | None
    # Read from the model to build avatar_url; never serialized.
    avatar_key: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avatar_url(self) -> str | None:
        """Same-origin URL of the user's own photo, or None when they have none."""
        version = avatar_version(self.avatar_key)
        return f"/api/v1/me/avatar?v={version}" if version else None
