"""API schemas (DTOs) — the public, versioned contract (ADR-014).

These models are deliberately separate from the ORM models. The DB schema can
evolve without breaking the wire contract, and we never accidentally leak an
internal column (e.g. ``secret_hash``) to a client.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from ..db.models import VerificationStatus, VerifierType
from ..domain.rbac import Role

Slug = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$", to_lower=True)
]
Name = Annotated[str, StringConstraints(min_length=1, max_length=255, strip_whitespace=True)]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Pagination ------------------------------------------------------------- #
class Page(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    limit: int


# --- Organizations ---------------------------------------------------------- #
class OrgCreate(BaseModel):
    name: Name
    slug: Slug


class OrgOut(_ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: _dt.datetime


# --- Workspaces ------------------------------------------------------------- #
class WorkspaceCreate(BaseModel):
    name: Name
    slug: Slug


class WorkspaceOut(_ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    created_at: _dt.datetime


# --- Projects --------------------------------------------------------------- #
class ProjectCreate(BaseModel):
    name: Name
    slug: Slug
    description: str | None = Field(default=None, max_length=4096)


class ProjectOut(_ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    created_at: _dt.datetime


# --- API keys --------------------------------------------------------------- #
class ApiKeyCreate(BaseModel):
    name: Name
    role: Role = Role.SERVICE
    project_id: uuid.UUID | None = None
    expires_at: _dt.datetime | None = None


class ApiKeyOut(_ORMModel):
    id: uuid.UUID
    name: str
    key_id: str
    role: Role
    project_id: uuid.UUID | None
    last_used_at: _dt.datetime | None
    expires_at: _dt.datetime | None
    revoked_at: _dt.datetime | None
    created_at: _dt.datetime


class ApiKeyCreated(ApiKeyOut):
    # The plaintext key, returned EXACTLY ONCE at creation.
    secret: str = Field(description="Full API key. Store securely; not retrievable later.")


# --- Verifiers -------------------------------------------------------------- #
class VerifierCreate(BaseModel):
    name: Name
    slug: Slug
    verifier_type: VerifierType
    definition: dict[str, Any] = Field(
        default_factory=dict,
        description="Verifier spec interpreted by the verification engine.",
    )


class VerifierOut(_ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    version: int
    verifier_type: VerifierType
    definition: dict[str, Any]
    robustness_score: float | None
    is_active: bool
    created_at: _dt.datetime


# --- Verification runs ------------------------------------------------------ #
class VerificationSubmit(BaseModel):
    verifier_id: uuid.UUID
    artifact_ref: str = Field(
        description="S3 key (or inline ref) for the output/trajectory under test.",
        max_length=1024,
    )
    idempotency_key: str | None = Field(default=None, max_length=255)


class VerificationOut(_ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    verifier_id: uuid.UUID
    status: VerificationStatus
    score: float | None
    uncertainty: float | None
    passed: bool | None
    risk_score: float | None
    grader_breakdown: dict[str, Any]
    latency_ms: int | None
    created_at: _dt.datetime


class AuditRecordOut(_ORMModel):
    id: uuid.UUID
    chain_index: int
    event_type: str
    actor_type: str
    actor_id: str | None
    resource_type: str | None
    resource_id: str | None
    occurred_at: _dt.datetime
    prev_hash: str
    record_hash: str


# --- Auth ------------------------------------------------------------------- #
class TokenPair(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    # Echoed so a client knows which org the token is scoped to.
    org_id: uuid.UUID
    org_slug: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=256)]
    full_name: Name | None = None
    org_name: Name
    org_slug: Slug


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    # Required only if the user belongs to more than one organization.
    org_slug: Slug | None = None
