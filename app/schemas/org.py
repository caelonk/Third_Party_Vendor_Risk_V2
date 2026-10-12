"""Organization, membership, and invitation DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from ..models.base import Role


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    plan: str
    created_at: datetime


class OrgWithRole(OrgOut):
    """An org as seen by one of its members: their role plus the details the
    org's admins recorded about them."""

    role: Role
    employee_id: str | None = None
    team: str | None = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: EmailStr
    name: str | None
    role: Role
    employee_id: str | None = None
    team: str | None = None
    avatar_url: str | None = None


def _blank_to_none(value: str | None) -> str | None:
    cleaned = " ".join((value or "").split())
    return cleaned or None


class MemberUpdate(BaseModel):
    """Patch a member. Absent fields are left unchanged; blank or null clears
    ``employee_id`` / ``team``."""

    role: Role | None = None
    employee_id: str | None = Field(default=None, max_length=64)
    team: str | None = Field(default=None, max_length=100)

    _clean = field_validator("employee_id", "team")(_blank_to_none)


class InviteCreate(BaseModel):
    email: EmailStr
    role: Role = Role.member


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: Role
    token: str
    expires_at: datetime
    accepted_at: datetime | None
