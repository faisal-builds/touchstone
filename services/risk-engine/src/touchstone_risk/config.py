"""Risk-engine configuration (``TOUCHSTONE_RISK_`` env prefix)."""

from __future__ import annotations

import enum
from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, enum.Enum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOUCHSTONE_RISK_", env_file=".env", extra="ignore"
    )

    service_name: str = "risk-engine"
    environment: Environment = Environment.LOCAL
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://touchstone:touchstone@localhost:5432/touchstone"
    )
    redpanda_brokers: str = "localhost:19092"
    consumer_group: str = "risk-engine"
    max_concurrency: int = 8
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
