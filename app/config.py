"""Application settings, loaded from the environment (never hard-coded).

Secrets (``JWT_SECRET``, ``APP_ENCRYPTION_KEY``, the system ``NVD_API_KEY``, SMTP
credentials) come from the platform's environment/secret store. ``.env`` is read
in development only; production injects real environment variables.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Environment
    env: str = Field(default="development")
    debug: bool = Field(default=False)

    # Datastores
    database_url: str = Field(
        default="postgresql+psycopg://vendor_risk:vendor_risk@localhost:5432/vendor_risk"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Auth
    jwt_secret: str = Field(default="dev-insecure-change-me-please-override-in-env")
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_seconds: int = Field(default=15 * 60)          # 15 minutes
    refresh_token_ttl_seconds: int = Field(default=14 * 24 * 3600)  # 14 days
    cookie_secure: bool = Field(default=True)
    cookie_domain: str | None = Field(default=None)

    # Secret encryption (envelope key for org integration secrets). A urlsafe
    # base64 32-byte Fernet key; generate one per environment.
    app_encryption_key: str | None = Field(default=None)

    # NVD system fallback key (per-org keys are stored encrypted per tenant).
    nvd_api_key: str | None = Field(default=None)

    # CORS: comma-free list via env as JSON or a single origin string.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # SMTP defaults (per-org overrides live in org_integrations).
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ("production", "prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()
