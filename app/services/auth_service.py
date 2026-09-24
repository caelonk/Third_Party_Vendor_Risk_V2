"""Registration and authentication."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Organization, User, UserPreference
from ..security import hash_password, verify_password
from . import org_service
from .exceptions import AuthError, ConflictError


def register(
    db: Session,
    *,
    email: str,
    password: str,
    name: str | None = None,
    org_name: str | None = None,
) -> tuple[User, Organization]:
    """Create a password account (see :func:`create_account`). Commits."""
    return create_account(
        db, email=email, password_hash=hash_password(password), name=name, org_name=org_name
    )


def create_account(
    db: Session,
    *,
    email: str,
    password_hash: str | None,
    name: str | None = None,
    org_name: str | None = None,
) -> tuple[User, Organization]:
    """Create a user, their preferences, and a personal org they own. Commits.

    ``password_hash`` is None for accounts that sign in only through an
    identity provider; such users can't use the password form.
    """
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("Email is already registered")

    user = User(email=email, password_hash=password_hash, name=name)
    db.add(user)
    db.flush()
    db.add(UserPreference(user_id=user.id))
    db.commit()
    db.refresh(user)

    org = org_service.create_org(
        db, name=org_name or f"{name or email.split('@')[0]}'s Organization", owner=user
    )
    return user, org


def authenticate(db: Session, *, email: str, password: str) -> User:
    """Return the user on valid credentials, else raise AuthError."""
    email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.password_hash or not user.is_active:
        raise AuthError("Invalid email or password")
    if not verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return user
