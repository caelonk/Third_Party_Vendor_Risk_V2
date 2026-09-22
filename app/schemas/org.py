"""Organization, membership, and invitation DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    role: Role


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: EmailStr
    name: str | None
    role: Role


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


class RoleUpdate(BaseModel):
    role: Role
