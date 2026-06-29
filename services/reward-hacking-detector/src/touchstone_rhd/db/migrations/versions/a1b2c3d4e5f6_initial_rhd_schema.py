"""initial rhd schema

Creates RHD's own tables (robustness_evaluations, exploits, verifier_refs) from
the repository metadata, which is the single source of truth for the schema.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

from touchstone_rhd.knowledge.repository import metadata as rhd_metadata

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    rhd_metadata.create_all(op.get_bind())


def downgrade() -> None:
    rhd_metadata.drop_all(op.get_bind())
