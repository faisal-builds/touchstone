"""Reward-hacking-detector configuration (``TOUCHSTONE_RHD_`` env prefix)."""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from touchstone_verify.sandbox.base import IsolationBackend as SandboxBackend


class Environment(str, enum.Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOUCHSTONE_RHD_", env_file=".env", extra="ignore"
    )

    service_name: str = "reward-hacking-detector"
    environment: Environment = Environment.LOCAL
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://touchstone:touchstone@localhost:5432/touchstone"
    )
    redpanda_brokers: str = "localhost:19092"
    consumer_group: str = "reward-hacking-detector"

    # Shared JWT settings so the RHD accepts the same user tokens the
    # control-plane issues (HS256, `org` claim), in addition to tsk_ API keys.
    jwt_secret: str = "change-me-in-prod-with-a-32-byte-minimum-secret"
    jwt_algorithm: str = "HS256"

    # Auth federation: tsk_ API keys are validated by calling the control-plane's
    # introspection endpoint (RHD never reads the control-plane api_keys table),
    # so RHD can run on a fully isolated database. Positive results are cached
    # briefly to avoid a round-trip + Argon2 verify on every request.
    control_plane_url: str = "http://localhost:8000"
    auth_cache_ttl_seconds: int = 30

    # Evaluation defaults.
    default_seed: int = 1337
    max_attacks: int = 2000
    max_concurrency: int = 16
    per_attack_timeout_s: float = 15.0
    # Auto-evaluate verifiers when they are registered (consume verifier.registered).
    auto_evaluate_on_register: bool = True
    # Model-generated attacks need a provider; off by default for offline runs.
    enable_model_attacks: bool = False
    # Worker retry policy.
    max_retries: int = 3
    retry_backoff_s: float = 2.0

    # Sandbox isolation backend (ADR-002). Attacks execute verifier code through
    # the verification-engine sandbox; production uses gVisor/Firecracker. Mirrors
    # the verification-engine knobs so both services isolate identically.
    sandbox_backend: SandboxBackend = SandboxBackend.SUBPROCESS
    sandbox_image: str = "touchstone/sandbox:latest"
    sandbox_allow_fallback: bool = False

    log_level: str = "INFO"

    # Observability: when set, OpenTelemetry traces are exported to this OTLP
    # endpoint. Unset (default) means tracing is a no-op — safe for dev/CI.
    otel_exporter_otlp_endpoint: str | None = None

    # HTTP API.
    api_host: str = "0.0.0.0"  # noqa: S104
    api_port: int = 8030


@lru_cache
def get_settings() -> Settings:
    return Settings()
