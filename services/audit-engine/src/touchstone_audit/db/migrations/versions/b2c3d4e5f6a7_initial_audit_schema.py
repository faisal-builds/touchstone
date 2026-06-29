"""initial audit schema

Creates the audit-engine's own ``audit_records`` table from the repository
metadata, which is the single source of truth for the schema.

Revision ID: b2c3d4e5f6a7
Revises:
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

from touchstone_audit.repository import metadata as audit_metadata

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    audit_metadata.create_all(op.get_bind())


def downgrade() -> None:
    audit_metadata.drop_all(op.get_bind())
