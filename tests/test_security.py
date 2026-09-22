"""Auth primitives: password hashing, JWT round-trip, secret encryption."""
import jwt
import pytest

from app import security
from app.config import get_settings


def test_password_hash_and_verify():
    h = security.hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert security.verify_password("s3cret-pw", h)
    assert not security.verify_password("wrong", h)


def test_access_token_roundtrip():
    token = security.create_access_token(42, org=7)
    claims = security.decode_token(token)
    assert claims["sub"] == "42"
    assert claims["type"] == "access"
    assert claims["org"] == 7


def test_refresh_token_is_typed():
    claims = security.decode_token(security.create_refresh_token(1))
    assert claims["type"] == "refresh"


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "access_token_ttl_seconds", -1, raising=False)
    # Rebuild a token with a negative TTL by encoding directly.
    token = security._encode({"sub": "1", "type": "access"}, ttl_seconds=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_token(token)


def test_org_secret_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", security.generate_encryption_key())
    get_settings.cache_clear()
    try:
        ct = security.encrypt_secret("nvd-api-key-123")
        assert ct != "nvd-api-key-123"
        assert security.decrypt_secret(ct) == "nvd-api-key-123"
    finally:
        get_settings.cache_clear()
