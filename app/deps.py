"""Shared FastAPI dependencies: DB session, current user, org-scoping, RBAC.

Org scoping is centralized here: every ``/orgs/{org_id}/...`` route depends on
:func:`get_org_context`, which verifies the caller has a membership for that org
and loads their role. Services still take ``org_id`` explicitly, so a stray query
cannot leak across tenants.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Cookie, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Membership, Organization, Role, User

# Role hierarchy, lowest -> highest privilege.
_ROLE_RANK = {Role.viewer: 0, Role.member: 1, Role.admin: 2, Role.owner: 3}


@dataclass
class OrgContext:
    organization: Organization
    membership: Membership
    role: Role


def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_session),
) -> User:
    if not access_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    from .security import decode_token

    try:
        claims = decode_token(access_token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if claims.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_org_context(
    org_id: int = Path(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> OrgContext:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    membership = db.scalar(
        select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        # 404 (not 403) so membership is not disclosed to non-members.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgContext(organization=org, membership=membership, role=membership.role)


def require_role(minimum: Role):
    """Dependency factory enforcing a minimum role within the org context."""

    def _dep(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if _ROLE_RANK[ctx.role] < _ROLE_RANK[minimum]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role '{minimum.value}' or higher",
            )
        return ctx

    return _dep
