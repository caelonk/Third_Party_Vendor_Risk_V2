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

    # Public origin browsers use to reach the app. OAuth redirect URIs are built
    # from it (never from the request's Host header) and must match the ones
    # registered with the identity provider.
    app_base_url: str = Field(default="http://localhost:8080")
    # Sign in with Google (OIDC, authorization code + PKCE). Both unset -> the
    # "Continue with Google" button is hidden.
    google_client_id: str | None = Field(default=None)
    google_client_secret: str | None = Field(default=None)
    google_discovery_url: str = Field(
        default="https://accounts.google.com/.well-known/openid-configuration"
    )
    # Built-in stand-in for Google (development/tests): the same protocol, but
    # the "login" is a form that accepts any email. Ignored in production and
    # whenever real Google credentials are set.
    oidc_dev_provider: bool = Field(default=False)

    # Secret encryption (envelope key for org integration secrets). A urlsafe
    # base64 32-byte Fernet key; generate one per environment.
    app_encryption_key: str | None = Field(default=None)

    # NVD system fallback key (per-org keys are stored encrypted per tenant).
    nvd_api_key: str | None = Field(default=None)

    # Scheduled auto-sync (Celery Beat). The dispatcher fires on this cadence and
    # enqueues one task per due CPE prefix; a vendor is due when its own cadence
    # (org_integrations.sync_cadence_hours, else this default) has elapsed.
    beat_dispatch_interval_seconds: int = Field(default=300)   # dispatcher cron
    default_sync_cadence_hours: int = Field(default=24)        # when no org override
    # NVD rolling-window ceilings, enforced across workers by a Redis token bucket
    # keyed per API key (50 req / 30 s with a key, 5 req / 30 s without).
    nvd_rate_with_key_per_window: int = Field(default=50)
    nvd_rate_keyless_per_window: int = Field(default=5)
    nvd_rate_window_seconds: int = Field(default=30)
    nvd_rate_max_wait_seconds: float = Field(default=120.0)    # workers: give up if starved
    # Interactive calls (Sync button, CPE search) wait less, then answer 503.
    nvd_interactive_max_wait_seconds: float = Field(default=20.0)
    # Backfills (a product's first, expensive pull) must leave this share of the
    # bucket untouched, so incremental syncs and interactive calls always have room.
    nvd_backfill_reserve_fraction: float = Field(default=0.3)

    # Exports run on a worker, land in object storage, and download through a
    # short-lived signed URL. EXPORT_STORAGE "s3" = any S3-compatible store (AWS
    # S3, MinIO, R2, ...); "local" = a directory the API and worker share (dev
    # without an object store, and tests).
    export_storage: str = Field(default="local")  # local | s3
    export_local_dir: str = Field(default="var/exports")
    export_url_ttl_seconds: int = Field(default=300)          # signed-link lifetime
    export_retention_hours: int = Field(default=7 * 24)       # then the file is deleted
    export_max_active_per_org: int = Field(default=3)         # queued + running
    export_stale_after_minutes: int = Field(default=30)       # stuck job -> failed
    export_purge_interval_seconds: int = Field(default=3600)  # Beat cadence
    # Run the job inside the API request instead of on a worker. Only for local
    # development without Redis/Celery; never in production.
    export_run_inline: bool = Field(default=False)
    s3_bucket: str = Field(default="vendor-risk-exports")
    s3_region: str = Field(default="us-east-1")
    s3_endpoint_url: str | None = Field(default=None)  # unset -> AWS S3
    # The endpoint *browsers* reach, used only to sign download URLs. Differs
    # from S3_ENDPOINT_URL when workers talk to the store over a private network
    # (e.g. http://minio:9000 inside Docker vs http://localhost:9000 outside).
    s3_public_endpoint_url: str | None = Field(default=None)
    s3_access_key_id: str | None = Field(default=None)       # unset -> default AWS chain
    s3_secret_access_key: str | None = Field(default=None)
    s3_create_bucket: bool = Field(default=False)  # dev convenience; IAM rarely allows it

    # CORS: comma-free list via env as JSON or a single origin string.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # SMTP defaults (per-org overrides live in org_integrations).
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_from: str | None = Field(default=None)

    # Observability. LOG_FORMAT "auto" = JSON in production, readable text elsewhere.
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="auto")  # auto | json | text
    sentry_dsn: str | None = Field(default=None)  # unset -> Sentry fully disabled
    sentry_traces_sample_rate: float = Field(default=0.0)
    app_release: str | None = Field(default=None)  # e.g. the git SHA, set at deploy

    @property
    def is_production(self) -> bool:
        return self.env.lower() in ("production", "prod")

    @property
    def log_json(self) -> bool:
        fmt = self.log_format.lower()
        return fmt == "json" or (fmt == "auto" and self.is_production)


@lru_cache
def get_settings() -> Settings:
    return Settings()
