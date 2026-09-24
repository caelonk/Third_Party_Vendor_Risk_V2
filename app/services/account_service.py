"""The signed-in user's own sign-in methods: their password and linked identities.

An account created through Google has no password. To add one, the user first
unlinks Google (from Settings); only then can a password be created. That order
is enforced here, not just in the UI. An account that already has a password
changes it by proving the current one.

Unlinking never locks anyone out for good: signing in with Google again links
the identity back (the provider still vouches for the verified email; see
:mod:`app.services.sso_service`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, UserIdentity
from ..security import hash_password, verify_password
from .exceptions import ConflictError, NotFoundError, ValidationError

log = logging.getLogger(__name__)

PROVIDER_NAMES = {"google": "Google"}


@dataclass
class SignInMethods:
    has_password: bool
    identities: list[UserIdentity]


def sign_in_methods(db: Session, user: User) -> SignInMethods:
    identities = db.scalars(
        select(UserIdentity)
        .where(UserIdentity.user_id == user.id)
        .order_by(UserIdentity.provider)
    ).all()
    return SignInMethods(has_password=bool(user.password_hash), identities=list(identities))


def unlink_identity(db: Session, user: User, provider: str) -> None:
    link = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id, UserIdentity.provider == provider
        )
    )
    if link is None:
        raise NotFoundError(f"No {PROVIDER_NAMES.get(provider, provider)} account is linked.")
    db.delete(link)
    db.commit()
    log.info(
        "identity unlinked: user %d, %s (has password: %s)",
        user.id, provider, bool(user.password_hash),
        extra={"user_id": user.id, "provider": provider},
    )


def set_password(
    db: Session, user: User, *, current_password: str | None, new_password: str
) -> bool:
    """Create or change the user's password. Returns True if it was created.

    * Has a password: the current one must be given and correct.
    * No password but a linked identity: refused; unlink first.
    * No password and nothing linked (just unlinked): create it.
    """
    if user.password_hash:
        if not current_password or not verify_password(current_password, user.password_hash):
            raise ValidationError("Your current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise ValidationError("Choose a new password that differs from your current one.")
        created = False
    else:
        linked = db.scalar(select(UserIdentity.provider).where(UserIdentity.user_id == user.id))
        if linked is not None:
            name = PROVIDER_NAMES.get(linked, linked)
            raise ConflictError(
                f"This account signs in with {name}. Unlink {name} before creating a password."
            )
        created = True

    user.password_hash = hash_password(new_password)
    db.commit()
    log.info(
        "password %s: user %d", "created" if created else "changed", user.id,
        extra={"user_id": user.id},
    )
    return created
