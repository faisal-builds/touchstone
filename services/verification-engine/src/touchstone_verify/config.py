"""Verification-engine configuration.

Shares the platform's ``TOUCHSTONE_`` env convention but uses the
``TOUCHSTONE_VERIFY_`` prefix for engine-specific knobs so the two services can
coexist in one environment file without collisions.
"""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sandbox.base import IsolationBackend as SandboxBackend


class Environment(str, enum.Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOUCHSTONE_VERIFY_", env_file=".env", extra="ignore"
    )

    service_name: str = "verification-engine"
    environment: Environment = Environment.LOCAL

    # Shared datastore (read verifier defs, write run results).
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://touchstone:touchstone@localhost:5432/touchstone"
    )
    redpanda_brokers: str = "localhost:19092"
    consumer_group: str = "verification-engine"

    # Concurrency: how many verifications execute in parallel per worker.
    max_concurrency: int = 8
    # Default per-verification wall-clock budget.
    default_timeout_s: float = 30.0

    # Sandbox isolation backend (ADR-002). ``subprocess`` is the dev/CI baseline;
    # ``gvisor`` / ``firecracker`` are the production isolation boundaries.
    sandbox_backend: SandboxBackend = SandboxBackend.SUBPROCESS
    sandbox_image: str = "touchstone/sandbox:latest"
    # Permit degrading a hardened backend to subprocess if its runtime is absent.
    # Keep False in production so a missing runtime fails loudly.
    sandbox_allow_fallback: bool = False

    # Model judge provider (optional; mock used when absent).
    anthropic_api_key: SecretStr | None = None
    default_judge_model: str = "claude-3-5-sonnet-latest"

    # Object storage for artifacts. file:// for local dev; s3:// in prod.
    artifact_store_uri: str = "file:///tmp/touchstone-artifacts"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
