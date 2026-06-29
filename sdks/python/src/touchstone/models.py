"""Typed response models for the Touchstone SDK.

These mirror the control-plane's response schemas but are defined here so the SDK
is a standalone package with no dependency on server code. Pydantic gives callers
real types, validation, and IDE autocompletion instead of raw dicts.
"""

from __future__ import annotations

import datetime as _dt
import enum
import uuid

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class VerifierType(str, enum.Enum):
    CODE = "code"
    MODEL = "model"
    PROCESS = "process"
    HYBRID = "hybrid"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (VerificationStatus.COMPLETED, VerificationStatus.FAILED)


class TokenPair(_Model):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    org_id: uuid.UUID
    org_slug: str


class ApiKey(_Model):
    id: uuid.UUID
    name: str
    key_id: str
    role: str
    project_id: uuid.UUID | None = None
    last_used_at: _dt.datetime | None = None
    expires_at: _dt.datetime | None = None
    revoked_at: _dt.datetime | None = None
    created_at: _dt.datetime


class ApiKeyCreated(ApiKey):
    # The full plaintext key — shown exactly once at creation.
    secret: str


class Workspace(_Model):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    created_at: _dt.datetime


class Project(_Model):
    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    created_at: _dt.datetime


class Verifier(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    version: int
    verifier_type: VerifierType
    definition: dict
    robustness_score: float | None = None
    is_active: bool
    created_at: _dt.datetime


class Verification(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    verifier_id: uuid.UUID
    status: VerificationStatus
    score: float | None = None
    uncertainty: float | None = None
    passed: bool | None = None
    risk_score: float | None = None
    grader_breakdown: dict = {}
    latency_ms: int | None = None
    created_at: _dt.datetime
