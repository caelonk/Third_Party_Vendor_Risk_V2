"""The signed-in user's own profile: display name, photo, and recent sign-ins.

**Photo.** An upload is untrusted bytes, so it is never stored as received. It is
decoded with a short allow-list of formats, size-checked before the pixels are
read, then re-encoded as a small square WebP. Re-encoding drops everything that
isn't the picture (EXIF/GPS metadata, appended data, odd containers), and the
output type and size are always the same. The file lives in object storage; the
API serves it same-origin and only to signed-in users allowed to see it.

**Sign-ins.** Each successful sign-in is recorded with its method, address and
browser so a user can spot one they don't recognize. Only the newest few are
kept. Recording is best-effort: a failure here must never block a sign-in.
"""
from __future__ import annotations

import io
import logging
import secrets
from datetime import UTC, datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import LoginEvent, User
from .exceptions import NotFoundError, ValidationError
from .object_storage import ObjectNotFoundError, ObjectStorage

log = logging.getLogger(__name__)

MAX_NAME_LENGTH = 200

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 40_000_000  # ~6300 x 6300; checked from the header, before decoding
AVATAR_SIZE = 256               # stored as a square of this many pixels
AVATAR_CONTENT_TYPE = "image/webp"
_AVATAR_FORMATS = ("PNG", "JPEG", "WEBP")
_UNREADABLE = "That file isn't an image we can read. Use a PNG, JPEG or WebP."

LOGIN_HISTORY_KEEP = 20   # per user; older rows are pruned on insert
LOGIN_HISTORY_SHOWN = 5
_MAX_USER_AGENT = 300
_MAX_IP = 45


# --------------------------------------------------------------------------- #
# Display name                                                                 #
# --------------------------------------------------------------------------- #
def update_name(db: Session, user: User, name: str | None) -> User:
    """Set the display name; blank clears it (the UI then falls back to the email)."""
    cleaned = " ".join((name or "").split())
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(f"Use at most {MAX_NAME_LENGTH} characters.")
    user.name = cleaned or None
    db.commit()
    db.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# Photo                                                                        #
# --------------------------------------------------------------------------- #
def process_avatar(data: bytes) -> bytes:
    """Validate an uploaded image and return it as a square WebP. Raises
    ``ValidationError`` with a message fit for the user."""
    if not data:
        raise ValidationError("Choose an image to upload.")
    if len(data) > MAX_AVATAR_BYTES:
        raise ValidationError(
            f"That image is larger than {MAX_AVATAR_BYTES // (1024 * 1024)} MB. Choose a smaller one."
        )
    try:
        with Image.open(io.BytesIO(data), formats=_AVATAR_FORMATS) as source:
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise ValidationError("That image's dimensions are too large. Choose a smaller one.")
            upright = ImageOps.exif_transpose(source)  # honour the camera's rotation flag
            has_alpha = "A" in upright.getbands() or "transparency" in upright.info
            square = ImageOps.fit(
                upright.convert("RGBA" if has_alpha else "RGB"),
                (AVATAR_SIZE, AVATAR_SIZE),
                Image.Resampling.LANCZOS,
            )
            out = io.BytesIO()
            square.save(out, "WEBP", quality=86, method=4)
            return out.getvalue()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError) as exc:
        # Not one of the allowed formats, truncated, or malformed.
        raise ValidationError(_UNREADABLE) from exc


def set_avatar(db: Session, user: User, data: bytes, storage: ObjectStorage) -> User:
    image = process_avatar(data)
    # A fresh key per upload: the URL changes with it, so caches never show a stale photo.
    key = f"avatars/{user.id}/{secrets.token_hex(12)}.webp"
    storage.put(key, image, content_type=AVATAR_CONTENT_TYPE)
    previous, user.avatar_key = user.avatar_key, key
    db.commit()
    db.refresh(user)
    _discard(storage, previous)
    log.info("avatar updated: user %d (%d bytes)", user.id, len(image),
             extra={"user_id": user.id})
    return user


def remove_avatar(db: Session, user: User, storage: ObjectStorage) -> User:
    previous, user.avatar_key = user.avatar_key, None
    db.commit()
    db.refresh(user)
    _discard(storage, previous)
    return user


def load_avatar(user: User, storage: ObjectStorage) -> bytes:
    if not user.avatar_key:
        raise NotFoundError("No profile photo.")
    try:
        return storage.get(user.avatar_key)
    except ObjectNotFoundError as exc:
        raise NotFoundError("No profile photo.") from exc


def _discard(storage: ObjectStorage, key: str | None) -> None:
    if not key:
        return
    try:
        storage.delete(key)
    except Exception:  # an orphaned 10 KB file is not worth failing the request
        log.warning("could not delete old avatar %s", key, exc_info=True)


# --------------------------------------------------------------------------- #
# Recent sign-ins                                                              #
# --------------------------------------------------------------------------- #
def record_login(
    db: Session, user: User, *, method: str, ip: str | None, user_agent: str | None
) -> None:
    """Record a successful sign-in. Never raises."""
    try:
        db.add(LoginEvent(
            user_id=user.id,
            method=method[:32],
            ip=(ip or "")[:_MAX_IP] or None,
            user_agent=(user_agent or "")[:_MAX_USER_AGENT] or None,
            created_at=datetime.now(UTC),
        ))
        db.flush()
        keep = (
            select(LoginEvent.id)
            .where(LoginEvent.user_id == user.id)
            .order_by(LoginEvent.created_at.desc(), LoginEvent.id.desc())
            .limit(LOGIN_HISTORY_KEEP)
        )
        db.execute(
            delete(LoginEvent)
            .where(LoginEvent.user_id == user.id, LoginEvent.id.not_in(keep))
            .execution_options(synchronize_session=False)
        )
        db.commit()
    except Exception:
        db.rollback()
        log.warning("could not record sign-in for user %d", user.id, exc_info=True)


def recent_logins(db: Session, user: User, limit: int = LOGIN_HISTORY_SHOWN) -> list[LoginEvent]:
    return list(
        db.scalars(
            select(LoginEvent)
            .where(LoginEvent.user_id == user.id)
            .order_by(LoginEvent.created_at.desc(), LoginEvent.id.desc())
            .limit(limit)
        )
    )
