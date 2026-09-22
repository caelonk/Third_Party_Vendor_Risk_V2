"""Organization, membership, and invitation operations."""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Invitation, Membership, Organization, Role, User
from .exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError

INVITE_TTL_DAYS = 7


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def _unique_slug(db: Session, base: str) -> str:
    slug = base
    n = 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_org(db: Session, *, name: str, owner: User, slug: str | None = None) -> Organization:
    """Create an org and make ``owner`` its owner. Commits."""
    org = Organization(name=name, slug=_unique_slug(db, slugify(slug or name)))
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=owner.id, role=Role.owner))
    db.commit()
    db.refresh(org)
    return org


def list_orgs_for_user(db: Session, user: User) -> list[tuple[Organization, Role]]:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return [(org, role) for org, role in rows]


def list_members(db: Session, org_id: int) -> list[tuple[User, Role]]:
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
        .order_by(User.email)
    ).all()
    return [(user, role) for user, role in rows]


def add_member(db: Session, org_id: int, *, user_id: int, role: Role) -> Membership:
    if db.get(User, user_id) is None:
        raise NotFoundError("User not found")
    existing = db.scalar(
        select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id
        )
    )
    if existing is not None:
        raise ConflictError("User is already a member of this organization")
    membership = Membership(org_id=org_id, user_id=user_id, role=role)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def set_member_role(db: Session, org_id: int, *, user_id: int, role: Role) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id
        )
    )
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.role is Role.owner and role is not Role.owner and _owner_count(db, org_id) <= 1:
        raise ConflictError("Cannot demote the last owner")
    membership.role = role
    db.commit()
    db.refresh(membership)
    return membership


def remove_member(db: Session, org_id: int, *, user_id: int) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.org_id == org_id, Membership.user_id == user_id
        )
    )
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.role is Role.owner and _owner_count(db, org_id) <= 1:
        raise ConflictError("Cannot remove the last owner")
    db.delete(membership)
    db.commit()


def _owner_count(db: Session, org_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == Role.owner)
        )
        or 0
    )


# --------------------------------------------------------------------------- #
# Invitations                                                                  #
# --------------------------------------------------------------------------- #
def create_invitation(
    db: Session, org_id: int, *, email: str, role: Role, invited_by: int
) -> Invitation:
    email = email.strip().lower()
    # If the user already exists and is a member, reject.
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        member = db.scalar(
            select(Membership).where(
                Membership.org_id == org_id, Membership.user_id == existing_user.id
            )
        )
        if member is not None:
            raise ConflictError("User is already a member of this organization")

    invite = Invitation(
        org_id=org_id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
        invited_by=invited_by,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def list_invitations(db: Session, org_id: int) -> list[Invitation]:
    return list(
        db.scalars(
            select(Invitation)
            .where(Invitation.org_id == org_id, Invitation.accepted_at.is_(None))
            .order_by(Invitation.created_at.desc())
        )
    )


def accept_invitation(db: Session, *, token: str, user: User) -> Membership:
    invite = db.scalar(select(Invitation).where(Invitation.token == token))
    if invite is None:
        raise NotFoundError("Invitation not found")
    if invite.accepted_at is not None:
        raise ConflictError("Invitation already accepted")
    # SQLite returns naive datetimes even for tz-aware columns; normalize to UTC.
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise ValidationError("Invitation has expired")
    if invite.email != user.email.strip().lower():
        raise PermissionDeniedError("This invitation was issued to a different email")

    membership = db.scalar(
        select(Membership).where(
            Membership.org_id == invite.org_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        membership = Membership(org_id=invite.org_id, user_id=user.id, role=invite.role)
        db.add(membership)
    invite.accepted_at = datetime.now(UTC)
    db.commit()
    db.refresh(membership)
    return membership
