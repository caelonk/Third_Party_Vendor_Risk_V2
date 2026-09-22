"""Per-user preferences: theme and the customizable dashboard layout.

The 5-widget maximum is enforced here (service layer), not only in the UI or the
request schema, so no code path can persist an over-cap board.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Theme, User, UserPreference
from ..models.user import MAX_DASHBOARD_WIDGETS
from .exceptions import ValidationError


def get_or_create(db: Session, user: User) -> UserPreference:
    prefs = db.get(UserPreference, user.id)
    if prefs is None:
        prefs = UserPreference(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def update(
    db: Session,
    user: User,
    *,
    theme: Theme | None = None,
    dashboard_layout: list[dict] | None = None,
) -> UserPreference:
    prefs = get_or_create(db, user)
    if theme is not None:
        prefs.theme = theme
    if dashboard_layout is not None:
        if len(dashboard_layout) > MAX_DASHBOARD_WIDGETS:
            raise ValidationError(
                f"A dashboard may have at most {MAX_DASHBOARD_WIDGETS} widgets"
            )
        prefs.dashboard_layout = dashboard_layout
    db.commit()
    db.refresh(prefs)
    return prefs
