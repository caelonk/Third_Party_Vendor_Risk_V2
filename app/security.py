"""Password hashing, JWT tokens, and envelope encryption for org secrets.

* Passwords: Argon2id via argon2-cffi.
* Sessions: signed JWTs (HS256) delivered in httpOnly cookies (see api/auth).
* Org secrets: Fernet symmetric encryption keyed by ``APP_ENCRYPTION_KEY`` — only
  ciphertext is stored; plaintext never touches the database or logs.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet

from .config import get_settings

_ph = PasswordHasher()


# --------------------------------------------------------------------------- #
# Passwords                                                                    #
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# --------------------------------------------------------------------------- #
# JWT                                                                          #
# --------------------------------------------------------------------------- #
def _encode(claims: dict[str, Any], ttl_seconds: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + timedelta(seconds=ttl_seconds)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, **extra: Any) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "type": "access", **extra}, settings.access_token_ttl_seconds
    )


def create_refresh_token(user_id: int, **extra: Any) -> str:
    settings = get_settings()
    return _encode(
        {"sub": str(user_id), "type": "refresh", **extra}, settings.refresh_token_ttl_seconds
    )


def decode_token(token: str) -> dict[str, Any]:
    """Return the token claims, or raise ``jwt.InvalidTokenError`` (incl. expiry)."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --------------------------------------------------------------------------- #
# Envelope encryption for org integration secrets                             #
# --------------------------------------------------------------------------- #
def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.app_encryption_key:
        raise RuntimeError("APP_ENCRYPTION_KEY is not configured")
    return Fernet(settings.app_encryption_key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def generate_encryption_key() -> str:
    """Generate a new Fernet key (for provisioning APP_ENCRYPTION_KEY)."""
    return Fernet.generate_key().decode()
