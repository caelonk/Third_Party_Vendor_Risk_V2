"""Organization, membership, and invitation endpoints (org-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_current_user, get_org_context, require_role
from ..models import Role, User
from ..schemas.org import (
    InviteCreate,
    InviteOut,
    MemberOut,
    OrgCreate,
    OrgOut,
    OrgWithRole,
    RoleUpdate,
)
from ..services import org_service

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _with_role(org, role: Role) -> OrgWithRole:
    return OrgWithRole(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan,
        created_at=org.created_at, role=role,
    )


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
def create_org(
    body: OrgCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> OrgOut:
    org = org_service.create_org(db, name=body.name, owner=user, slug=body.slug)
    return OrgOut.model_validate(org)


@router.get("", response_model=list[OrgWithRole])
def list_orgs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[OrgWithRole]:
    return [_with_role(org, role) for org, role in org_service.list_orgs_for_user(db, user)]


@router.get("/{org_id}", response_model=OrgWithRole)
def get_org(ctx: OrgContext = Depends(get_org_context)) -> OrgWithRole:
    return _with_role(ctx.organization, ctx.role)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org(
    ctx: OrgContext = Depends(require_role(Role.owner)),
    db: Session = Depends(get_session),
) -> None:
    db.delete(ctx.organization)
    db.commit()


# --------------------------------------------------------------------------- #
# Members                                                                      #
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[MemberOut]:
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=role)
        for u, role in org_service.list_members(db, ctx.organization.id)
    ]


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
def set_member_role(
    user_id: int,
    body: RoleUpdate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> MemberOut:
    m = org_service.set_member_role(db, ctx.organization.id, user_id=user_id, role=body.role)
    user = db.get(User, user_id)
    assert user is not None  # set_member_role raises NotFoundError if absent
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=m.role)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: int,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> None:
    org_service.remove_member(db, ctx.organization.id, user_id=user_id)


# --------------------------------------------------------------------------- #
# Invitations                                                                  #
# --------------------------------------------------------------------------- #
@router.post(
    "/{org_id}/invitations", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
def create_invitation(
    body: InviteCreate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> InviteOut:
    invite = org_service.create_invitation(
        db, ctx.organization.id, email=body.email, role=body.role,
        invited_by=ctx.membership.user_id,
    )
    return InviteOut.model_validate(invite)


@router.get("/{org_id}/invitations", response_model=list[InviteOut])
def list_invitations(
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> list[InviteOut]:
    return [InviteOut.model_validate(i) for i in org_service.list_invitations(db, ctx.organization.id)]
