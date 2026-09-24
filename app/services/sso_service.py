"""Map a verified external identity (Google) to a user account.

Rules, in order:

1. A known identity (provider + subject) signs in as its linked user.
2. Otherwise, a user with the same email gets the identity linked — only
   because the provider asserts the email is *verified*. Without that anyone
   could create a provider account claiming a victim's address.
3. Otherwise a new account is created, exactly as registration does (user,
   preferences, and a personal org they own), with no password.

A user can link one identity per provider; a *different* Google account with
the same email is refused rather than silently taking over.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import User, UserIdentity
from . import auth_service
from .exceptions import ConflictError
from .oidc import OidcError, OidcIdentity

log = logging.getLogger(__name__)

Outcome = Literal["signed_in", "linked", "created"]


def _find_identity(db: Session, identity: OidcIdentity) -> UserIdentity | None:
    return db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == identity.provider,
            UserIdentity.subject == identity.subject,
        )
    )


def _touch(link: UserIdentity, user: User, identity: OidcIdentity, now: datetime) -> None:
    link.email = identity.email
    link.last_login_at = now
    user.last_login_at = now
    if not user.name and identity.name:
        user.name = identity.name


def resolve_user(
    db: Session, identity: OidcIdentity, *, _retried: bool = False
) -> tuple[User, Outcome]:
    """Return the account for this identity, linking or creating as needed. Commits.

    Raises ``OidcError`` with code ``unverified``, ``disabled`` or ``conflict``.
    """
    if not identity.email_verified:
        raise OidcError("unverified", f"{identity.provider} email not verified")
    now = datetime.now(UTC)

    link = _find_identity(db, identity)
    if link is not None:
        if not link.user.is_active:
            raise OidcError("disabled", f"user {link.user_id} is inactive")
        _touch(link, link.user, identity, now)
        db.commit()
        return link.user, "signed_in"

    user = db.scalar(select(User).where(User.email == identity.email))
    outcome: Outcome = "linked"
    if user is not None:
        if not user.is_active:
            raise OidcError("disabled", f"user {user.id} is inactive")
        already = db.scalar(
            select(UserIdentity.id).where(
                UserIdentity.user_id == user.id, UserIdentity.provider == identity.provider
            )
        )
        if already is not None:
            raise OidcError(
                "conflict", f"user {user.id} is linked to another {identity.provider} account"
            )
    else:
        try:
            user, _org = auth_service.create_account(
                db, email=identity.email, password_hash=None, name=identity.name
            )
        except ConflictError:
            # A concurrent first sign-in created the account a moment ago.
            db.rollback()
            if _retried:
                raise
            return resolve_user(db, identity, _retried=True)
        outcome = "created"

    link = UserIdentity(user_id=user.id, provider=identity.provider, subject=identity.subject)
    db.add(link)
    _touch(link, user, identity, now)
    try:
        db.commit()
    except IntegrityError:
        # Two first sign-ins raced; the other one linked it. Use that link.
        db.rollback()
        existing = _find_identity(db, identity)
        if existing is None:
            raise
        return existing.user, "signed_in"
    log.info(
        "sso %s: user %d via %s", outcome, user.id, identity.provider,
        extra={"sso_outcome": outcome, "user_id": user.id, "provider": identity.provider},
    )
    return user, outcome
