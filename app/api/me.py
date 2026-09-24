"""The current user: preferences (theme + dashboard layout) and sign-in methods
(password, linked Google account)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas.account import LinkedIdentityOut, PasswordUpdate, SignInMethodsOut
from ..schemas.preferences import PreferencesOut, PreferencesUpdate
from ..services import account_service, preferences_service

router = APIRouter(prefix="/me", tags=["me"])


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
