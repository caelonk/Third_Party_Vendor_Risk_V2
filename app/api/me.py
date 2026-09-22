"""Current-user preferences: theme + the customizable dashboard layout."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas.preferences import PreferencesOut, PreferencesUpdate
from ..services import preferences_service

router = APIRouter(prefix="/me", tags=["me"])


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
