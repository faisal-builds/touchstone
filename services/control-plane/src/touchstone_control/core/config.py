"""Application configuration (ADR-001..014).

All runtime configuration is loaded from the environment via pydantic-settings
so the service is 12-factor and the same image runs in every environment. There
are NO hardcoded secrets; production secrets are injected by Kubernetes from
AWS Secrets Manager (see deploy/).
"""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, enum.Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOUCHSTONE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Branding (decoupled per the naming decision) --------------------------
    product_name: str = "Touchstone"

    # --- Service identity ------------------------------------------------------
    service_name: str = "control-plane"
    environment: Environment = Environment.LOCAL
    debug: bool = False

    # --- HTTP ------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    # CORS origins allowed to call the API from the dashboard.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Datastores ------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://touchstone:touchstone@localhost:5432/touchstone"
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10
    # Audit records live in the audit-engine's own database after the per-service
    # split. The control-plane reads them through a read-only cross-database
    # connection; when unset this falls back to `database_url` (dev/shared-DB).
    audit_database_url: PostgresDsn | None = None
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")

    # --- Event backbone --------------------------------------------------------
    redpanda_brokers: str = "localhost:19092"

    # --- Security --------------------------------------------------------------
    # JWT signing key for dashboard sessions. MUST be overridden in prod.
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-change-me")
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 14
    # Argon2id parameters (OWASP-recommended baseline; tuned up in prod via env).
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 64 * 1024  # KiB
    argon2_parallelism: int = 2
    # Public, non-secret prefix that makes leaked keys greppable in logs/CI.
    api_key_prefix: str = "tsk"

    # --- Rate limiting ---------------------------------------------------------
    rate_limit_per_minute: int = 600
    rate_limit_burst: int = 100

    # --- Observability ---------------------------------------------------------
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str | None = None
    sentry_dsn: SecretStr | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _reject_default_secret_in_prod(cls, v: SecretStr, info):  # noqa: ANN001
        return v  # enforced at startup in app.py where env is also known

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def effective_audit_database_url(self) -> str:
        """The audit database DSN, falling back to the main DB when unset."""
        return str(self.audit_database_url or self.database_url)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Tests override via dependency injection."""
    return Settings()
