"""Relational data model for the control plane.

Tenancy hierarchy (every table below is hard-scoped to an organization):

    organizations
      ├─ memberships ──> users           (who can access the org, with a role)
      ├─ api_keys                         (machine principals)
      └─ workspaces
           └─ projects
                └─ verifiers              (the core product: a registered grader)
                     └─ verification_runs (each execution + its score/uncertainty)

Design notes:
  * Soft-delete via ``deleted_at`` on user-facing resources so an enterprise can
    recover from accidental deletion and so audit history is never orphaned.
  * All foreign keys are ``ON DELETE CASCADE`` within a tenant subtree to keep
    referential integrity, but org deletion is a deliberate, gated operation.
  * Enums are stored as native Postgres enums for integrity.
"""

from __future__ import annotations

import datetime as _dt
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...domain.rbac import Role
from ..base import Base, TimestampMixin, UUIDPkMixin


def _enum_values(enum_cls):
    """Persist native-enum columns by their .value (lowercase), not member name."""
    return [m.value for m in enum_cls]


class VerifierType(str, enum.Enum):
    """The three verifier families from the architecture (frozen)."""

    CODE = "code"  # deterministic check (tests, assertions)
    MODEL = "model"  # LLM-as-judge
    PROCESS = "process"  # trajectory / step-level supervision
    HYBRID = "hybrid"  # ensemble of the above


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Identity & tenancy
# --------------------------------------------------------------------------- #
class Organization(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Loose JSON for plan/limits to avoid schema churn during early iteration.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    deleted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    # Null for SSO-only users. Argon2id hash when password auth is enabled.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Membership(UUIDPkMixin, TimestampMixin, Base):
    """Join of a user to an organization with a role (the human RBAC binding)."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role", values_callable=_enum_values), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class ApiKey(UUIDPkMixin, TimestampMixin, Base):
    """Machine principal. Only the Argon2id hash of the secret is stored."""

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_id", name="uq_api_keys_key_id"),
        Index("ix_api_keys_org_active", "organization_id", "revoked_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Optional: bind a key to a single project (least privilege).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role", values_callable=_enum_values),
        nullable=False,
        default=Role.SERVICE,
    )
    last_used_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    organization: Mapped[Organization] = relationship(back_populates="api_keys")


# --------------------------------------------------------------------------- #
# Workspaces & projects
# --------------------------------------------------------------------------- #
class Workspace(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization] = relationship(back_populates="workspaces")
    projects: Mapped[list[Project]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class Project(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_project_ws_slug"),
        Index("ix_projects_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    verifiers: Mapped[list[Verifier]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# Verifier registry (the product's core entity)
# --------------------------------------------------------------------------- #
class Verifier(UUIDPkMixin, TimestampMixin, Base):
    """A registered, versioned grader.

    The ``definition`` JSON is the verifier spec interpreted by the
    verification-engine (code reference, judge prompt, rubric, ensemble config).
    ``robustness_score`` is the headline product metric — the verifier's measured
    resistance to reward hacking, updated by the reward-hacking-detector.
    """

    __tablename__ = "verifiers"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", "version", name="uq_verifier_proj_slug_ver"),
        CheckConstraint(
            "robustness_score >= 0 AND robustness_score <= 1",
            name="robustness_range",
        ),
        Index("ix_verifiers_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verifier_type: Mapped[VerifierType] = mapped_column(
        SAEnum(VerifierType, name="verifier_type", values_callable=_enum_values), nullable=False
    )
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Latest measured robustness against reward hacking (0..1). Null until tested.
    robustness_score: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    deleted_at: Mapped[_dt.datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="verifiers")


class VerificationRun(UUIDPkMixin, TimestampMixin, Base):
    """One execution of a verifier against one artifact.

    Postgres holds the authoritative record + result; the high-volume event
    stream (ClickHouse) holds the analytical copy. The S3 ``artifact_ref`` points
    at the raw trajectory/output under test.
    """

    __tablename__ = "verification_runs"
    __table_args__ = (
        Index("ix_runs_verifier_created", "verifier_id", "created_at"),
        Index("ix_runs_org_status", "organization_id", "status"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="score_range"),
        CheckConstraint(
            "uncertainty IS NULL OR (uncertainty >= 0 AND uncertainty <= 1)",
            name="uncertainty_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    verifier_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("verifiers.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", values_callable=_enum_values),
        nullable=False,
        default=VerificationStatus.PENDING,
    )
    artifact_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column()
    grader_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    risk_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # Idempotency: callers may pass a key so retried submits don't double-run.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True)
