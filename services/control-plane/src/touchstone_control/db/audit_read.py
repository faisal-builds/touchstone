"""Read-only access to the audit log, which lives in the audit-engine's database.

After the per-service-database split the ``audit_records`` table is owned and
written exclusively by the audit-engine in its own database. The control-plane no
longer maps it as an ORM model; instead it reads it here through a dedicated,
read-only engine bound to ``effective_audit_database_url`` (which falls back to
the control-plane database when a separate audit DB is not configured, e.g. dev).

This keeps the cross-service dependency explicit and one-directional (read-only)
rather than a hidden shared schema.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..core.config import Settings

# A read-only projection of the audit-engine's table. Only the columns the API
# surfaces are needed; the audit-engine remains the single source of truth for
# the full schema and its constraints.
_metadata = MetaData()

audit_records = Table(
    "audit_records",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("chain_index", Integer),
    Column("event_type", String),
    Column("actor_type", String),
    Column("actor_id", String),
    Column("resource_type", String),
    Column("resource_id", String),
    Column("metadata", JSONB),
    Column("occurred_at", DateTime(timezone=True)),
    Column("prev_hash", String),
    Column("record_hash", String),
)


class AuditReader:
    """Owns a read-only engine for the audit database."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_settings(cls, settings: Settings) -> AuditReader:
        engine = create_async_engine(
            settings.effective_audit_database_url, pool_pre_ping=True
        )
        return cls(engine)

    async def list_for_org(
        self, organization_id: uuid.UUID, *, limit: int = 100
    ) -> list[Mapping[str, object]]:
        """Newest-first audit records for an organization (chain order)."""
        stmt = (
            select(
                audit_records.c.id,
                audit_records.c.chain_index,
                audit_records.c.event_type,
                audit_records.c.actor_type,
                audit_records.c.actor_id,
                audit_records.c.resource_type,
                audit_records.c.resource_id,
                audit_records.c.occurred_at,
                audit_records.c.prev_hash,
                audit_records.c.record_hash,
            )
            .where(audit_records.c.organization_id == organization_id)
            .order_by(audit_records.c.chain_index.desc())
            .limit(min(limit, 500))
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def dispose(self) -> None:
        await self._engine.dispose()
