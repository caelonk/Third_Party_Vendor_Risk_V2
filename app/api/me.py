"""The current user: profile (display name, photo, recent sign-ins), sign-in
methods (password, linked Google account), and preferences (theme + dashboard
layout)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas.account import LinkedIdentityOut, PasswordUpdate, SignInMethodsOut
from ..schemas.auth import UserOut
from ..schemas.preferences import PreferencesOut, PreferencesUpdate
from ..schemas.profile import LoginEventOut, ProfileUpdate
from ..services import account_service, object_storage, preferences_service, profile_service
from ..services.object_storage import ObjectStorage

router = APIRouter(prefix="/me", tags=["me"])

_AVATAR_UPLOAD_TYPES = {"image/png", "image/jpeg", "image/webp"}


def get_avatar_storage() -> ObjectStorage:
    return object_storage.get_storage()


def avatar_response(image: bytes) -> Response:
    """A stored photo. Its URL changes whenever the photo does (``?v=``), so the
    browser may keep it; ``private`` keeps it out of shared caches."""
    return Response(
        content=image,
        media_type=profile_service.AVATAR_CONTENT_TYPE,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --------------------------------------------------------------------------- #
# Profile                                                                      #
# --------------------------------------------------------------------------- #
@router.patch("", response_model=UserOut)
def update_profile(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> User:
    return profile_service.update_name(db, user, body.name)


def _limit_avatar_size(content_length: int | None = Header(default=None)) -> None:
    # A coarse early guard (the service checks the bytes actually received).
    if content_length is not None and content_length > profile_service.MAX_AVATAR_BYTES:
        limit_mb = profile_service.MAX_AVATAR_BYTES // (1024 * 1024)
        raise HTTPException(413, f"That image is larger than {limit_mb} MB.")


@router.put("/avatar", response_model=UserOut, dependencies=[Depends(_limit_avatar_size)])
def upload_avatar(
    # The image itself is the request body (no multipart dependency needed).
    image: bytes = Body(..., media_type="image/*"),
    content_type: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_avatar_storage),
) -> User:
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in _AVATAR_UPLOAD_TYPES:
        # The declared type only gates the request; the bytes are what get checked.
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a PNG, JPEG or WebP image."
        )
    return profile_service.set_avatar(db, user, image, storage)


@router.delete("/avatar", response_model=UserOut)
def delete_avatar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_avatar_storage),
) -> User:
    return profile_service.remove_avatar(db, user, storage)


@router.get("/avatar")
def get_avatar(
    user: User = Depends(get_current_user),
    storage: ObjectStorage = Depends(get_avatar_storage),
) -> Response:
    return avatar_response(profile_service.load_avatar(user, storage))


@router.get("/logins", response_model=list[LoginEventOut])
def recent_logins(
    limit: int = Query(default=profile_service.LOGIN_HISTORY_SHOWN, ge=1,
                       le=profile_service.LOGIN_HISTORY_KEEP),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[LoginEventOut]:
    return [
        LoginEventOut.model_validate(e) for e in profile_service.recent_logins(db, user, limit)
    ]


# --------------------------------------------------------------------------- #
# Sign-in methods                                                              #
# --------------------------------------------------------------------------- #
def _methods_out(db: Session, user: User) -> SignInMethodsOut:
    methods = account_service.sign_in_methods(db, user)
    return SignInMethodsOut(
        has_password=methods.has_password,
        identities=[
            LinkedIdentityOut(
                provider=i.provider, email=i.email, linked_at=i.created_at,
                last_login_at=i.last_login_at,
            )
            for i in methods.identities
        ],
    )


@router.get("/sign-in-methods", response_model=SignInMethodsOut)
def get_sign_in_methods(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SignInMethodsOut:
    return _methods_out(db, user)


@router.delete("/identities/{provider}", response_model=SignInMethodsOut)
def unlink_identity(
    provider: str = Path(..., pattern=r"^[a-z]{2,32}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> SignInMethodsOut:
    account_service.unlink_identity(db, user, provider)
    return _methods_out(db, user)


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    body: PasswordUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    account_service.set_password(
        db, user, current_password=body.current_password, new_password=body.new_password
    )


# --------------------------------------------------------------------------- #
# Preferences                                                                  #
# --------------------------------------------------------------------------- #
@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> PreferencesOut:
    prefs = preferences_service.get_or_create(db, user)
    return PreferencesOut.model_validate(prefs)


@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(
    body: PreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> PreferencesOut:
    layout = (
        [w.model_dump() for w in body.dashboard_layout]
        if body.dashboard_layout is not None
        else None
    )
    prefs = preferences_service.update(db, user, theme=body.theme, dashboard_layout=layout)
    return PreferencesOut.model_validate(prefs)
