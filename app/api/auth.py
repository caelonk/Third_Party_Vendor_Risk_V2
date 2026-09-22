"""Authentication endpoints. Tokens live in httpOnly cookies."""
from __future__ import annotations

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..db import get_session
from ..deps import get_current_user
from ..models import User
from ..schemas.auth import LoginRequest, RegisterRequest, UserOut
from ..security import decode_token
from ..services import auth_service
from ._cookies import clear_auth_cookies, set_auth_cookies

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    response: Response,
    db: Session = Depends(get_session),
) -> User:
    user, _org = auth_service.register(
        db,
        email=body.email,
        password=body.password,
        name=body.name,
        org_name=body.org_name,
    )
    set_auth_cookies(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_session),
) -> User:
    user = auth_service.authenticate(db, email=body.email, password=body.password)
    set_auth_cookies(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    clear_auth_cookies(response)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_session),
) -> None:
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        claims = decode_token(refresh_token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    if claims.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    set_auth_cookies(response, user.id)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
