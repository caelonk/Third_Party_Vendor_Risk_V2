"""Organization, membership, and invitation endpoints (org-scoped)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import OrgContext, get_current_user, get_org_context, require_role
from ..models import Membership, Organization, Role, User
from ..schemas.auth import avatar_version
from ..schemas.org import (
    InviteCreate,
    InviteOut,
    MemberOut,
    MemberUpdate,
    OrgCreate,
    OrgOut,
    OrgWithRole,
)
from ..services import audit_service, org_service, profile_service
from ..services.object_storage import ObjectStorage
from .me import avatar_response, get_avatar_storage

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _with_role(org: Organization, membership: Membership) -> OrgWithRole:
    return OrgWithRole(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan,
        created_at=org.created_at, role=membership.role,
        employee_id=membership.employee_id, team=membership.team,
    )


def _member_out(org_id: int, user: User, membership: Membership) -> MemberOut:
    version = avatar_version(user.avatar_key)
    return MemberOut(
        user_id=user.id, email=user.email, name=user.name, role=membership.role,
        employee_id=membership.employee_id, team=membership.team,
        avatar_url=(
            f"/api/v1/orgs/{org_id}/members/{user.id}/avatar?v={version}" if version else None
        ),
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
    return [_with_role(org, m) for org, m in org_service.list_orgs_for_user(db, user)]


@router.get("/{org_id}", response_model=OrgWithRole)
def get_org(ctx: OrgContext = Depends(get_org_context)) -> OrgWithRole:
    return _with_role(ctx.organization, ctx.membership)


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
    org_id = ctx.organization.id
    return [_member_out(org_id, u, m) for u, m in org_service.list_members(db, org_id)]


@router.get("/{org_id}/members/{user_id}/avatar")
def member_avatar(
    user_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_avatar_storage),
) -> Response:
    """A fellow member's photo. Org-scoped: only people in the same org can fetch it."""
    user, _membership = org_service.get_member(db, ctx.organization.id, user_id)
    return avatar_response(profile_service.load_avatar(user, storage))


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: int,
    body: MemberUpdate,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> MemberOut:
    """Change a member's role and/or the details admins keep about them."""
    org_id = ctx.organization.id
    patch = body.model_dump(exclude_unset=True)
    user, membership = org_service.get_member(db, org_id, user_id)

    role = patch.get("role")
    if role is not None and role != membership.role:
        membership = org_service.set_member_role(db, org_id, user_id=user_id, role=role)
        audit_service.record(
            db, org_id=org_id, actor_user_id=ctx.membership.user_id,
            action="member.role_changed", target_type="user", target_id=user_id,
            extra={"email": user.email, "role": membership.role.value},
        )

    details: dict[str, str | None] = {
        k: patch[k] for k in ("employee_id", "team") if k in patch
    }
    changed = sorted(k for k, v in details.items() if getattr(membership, k) != v)
    if changed:
        membership = org_service.update_member_details(
            db, org_id, user_id=user_id, changes=details
        )
        audit_service.record(
            db, org_id=org_id, actor_user_id=ctx.membership.user_id,
            action="member.updated", target_type="user", target_id=user_id,
            extra={"email": user.email, "fields": changed},
        )
    return _member_out(org_id, user, membership)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: int,
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> None:
    removed = db.get(User, user_id)
    org_service.remove_member(db, ctx.organization.id, user_id=user_id)
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="member.removed", target_type="user", target_id=user_id,
        extra={"email": removed.email} if removed else None,
    )


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
    audit_service.record(
        db, org_id=ctx.organization.id, actor_user_id=ctx.membership.user_id,
        action="member.invited", target_type="invitation", target_id=invite.id,
        extra={"email": body.email, "role": body.role.value},
    )
    return InviteOut.model_validate(invite)


@router.get("/{org_id}/invitations", response_model=list[InviteOut])
def list_invitations(
    ctx: OrgContext = Depends(require_role(Role.admin)),
    db: Session = Depends(get_session),
) -> list[InviteOut]:
    return [InviteOut.model_validate(i) for i in org_service.list_invitations(db, ctx.organization.id)]
