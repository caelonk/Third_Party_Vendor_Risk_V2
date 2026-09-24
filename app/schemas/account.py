"""The current user's sign-in methods (password + linked identities)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LinkedIdentityOut(BaseModel):
    provider: str
    email: str | None
    linked_at: datetime
    last_login_at: datetime | None


class SignInMethodsOut(BaseModel):
    has_password: bool
    identities: list[LinkedIdentityOut]


class PasswordUpdate(BaseModel):
    # Required only when the account already has a password.
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
