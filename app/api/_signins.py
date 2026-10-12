"""Record a successful sign-in from an HTTP request (see profile_service)."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import User
from ..services import profile_service


def record_sign_in(db: Session, request: Request, user: User, *, method: str) -> None:
    """Note who signed in, how, and from where. Best-effort: never raises.

    ``request.client`` is the browser's address: the app server only accepts
    connections from the reverse proxy and trusts its ``X-Forwarded-For``.
    """
    profile_service.record_login(
        db,
        user,
        method=method,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
