"""Audit-engine data access.

Appends records to a per-organization hash chain. Correctness under concurrency
is non-negotiable for an audit log, so each append takes a **per-org advisory
lock** for the duration of the transaction: this serializes writers for the same
org (preserving a single, gap-free chain) while letting different orgs proceed in
parallel. Re-delivery of the same source event is a no-op (idempotent on
``(organization_id, source_event_id)``).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    bindparam,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine

from .chain import GENESIS_HASH, AuditContent

# Fixed namespace for our advisory locks so they never collide with other
# subsystems' advisory locks that might share the key space.
_LOCK_NAMESPACE = 4242

_metadata = MetaData()

audit_records = Table(
    "audit_records", _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("chain_index", Integer),
    Column("source_event_id", UUID(as_uuid=True)),
    Column("event_type", String),
    Column("actor_type", String),
    Column("actor_id", String),
    Column("resource_type", String),
    Column("resource_id", String),
    Column("metadata", JSONB),
    Column("occurred_at", DateTime(timezone=True)),
    Column("prev_hash", String),
    Column("record_hash", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("organization_id", "chain_index", name="uq_audit_org_index"),
    UniqueConstraint(
        "organization_id", "source_event_id", name="uq_audit_org_source_event"
    ),
    UniqueConstraint("record_hash", name="uq_audit_record_hash"),
    Index("ix_audit_org_index", "organization_id", "chain_index"),
)

# Public alias + helpers: the audit-engine owns and creates its own schema
# (single-writer) after the per-service database split.
metadata = _metadata


async def create_schema(engine: AsyncEngine) -> None:
    """Create the audit-engine's own table (audit_records)."""
    async with engine.begin() as c:
        await c.run_sync(_metadata.create_all)


async def drop_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.run_sync(_metadata.drop_all)


@dataclasses.dataclass(frozen=True, slots=True)
class AppendInput:
    organization_id: uuid.UUID
    source_event_id: uuid.UUID
    event_type: str
    actor_type: str
    occurred_at: _dt.datetime
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class AppendResult:
    audit_id: uuid.UUID
    chain_index: int
    prev_hash: str
    record_hash: str
    created: bool  # False if this event was already recorded (idempotent no-op)


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, item: AppendInput) -> AppendResult:
        org = str(item.organization_id)
        async with self._engine.begin() as conn:
            # Serialize all writers for this org for the rest of the transaction.
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(:ns, hashtext(:org))").bindparams(
                    bindparam("ns", _LOCK_NAMESPACE), bindparam("org", org)
                )
            )

            # Idempotency: already recorded?
            existing = (
                await conn.execute(
                    select(
                        audit_records.c.id, audit_records.c.chain_index,
                        audit_records.c.prev_hash, audit_records.c.record_hash,
                    ).where(
                        audit_records.c.organization_id == item.organization_id,
                        audit_records.c.source_event_id == item.source_event_id,
                    )
                )
            ).first()
            if existing is not None:
                return AppendResult(existing.id, existing.chain_index,
                                    existing.prev_hash, existing.record_hash, created=False)

            # Tip of the chain for this org.
            tip = (
                await conn.execute(
                    select(audit_records.c.chain_index, audit_records.c.record_hash)
                    .where(audit_records.c.organization_id == item.organization_id)
                    .order_by(audit_records.c.chain_index.desc())
                    .limit(1)
                )
            ).first()
            chain_index = 0 if tip is None else tip.chain_index + 1
            prev_hash = GENESIS_HASH if tip is None else tip.record_hash

            metadata = item.metadata or {}
            content = AuditContent(
                organization_id=org,
                chain_index=chain_index,
                source_event_id=str(item.source_event_id),
                event_type=item.event_type,
                actor_type=item.actor_type,
                actor_id=item.actor_id,
                resource_type=item.resource_type,
                resource_id=item.resource_id,
                metadata=metadata,
                occurred_at=item.occurred_at,
                prev_hash=prev_hash,
            )
            record_hash = content.compute_hash()
            audit_id = uuid.uuid4()
            now = _dt.datetime.now(_dt.UTC)
            await conn.execute(
                audit_records.insert().values(
                    id=audit_id,
                    organization_id=item.organization_id,
                    chain_index=chain_index,
                    source_event_id=item.source_event_id,
                    event_type=item.event_type,
                    actor_type=item.actor_type,
                    actor_id=item.actor_id,
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    metadata=metadata,
                    occurred_at=item.occurred_at,
                    prev_hash=prev_hash,
                    record_hash=record_hash,
                    created_at=now,
                    updated_at=now,
                )
            )
            return AppendResult(audit_id, chain_index, prev_hash, record_hash, created=True)

    async def export_org(self, organization_id: uuid.UUID) -> list[dict]:
        """Return the org's full chain ordered by chain_index (for export/verify)."""
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(audit_records)
                    .where(audit_records.c.organization_id == organization_id)
                    .order_by(audit_records.c.chain_index.asc())
                )
            ).mappings().all()
        out: list[dict] = []
        for r in rows:
            out.append({
                "id": str(r["id"]),
                "organization_id": str(r["organization_id"]),
                "chain_index": r["chain_index"],
                "source_event_id": str(r["source_event_id"]),
                "event_type": r["event_type"],
                "actor_type": r["actor_type"],
                "actor_id": r["actor_id"],
                "resource_type": r["resource_type"],
                "resource_id": r["resource_id"],
                "metadata": r["metadata"],
                "occurred_at": r["occurred_at"],
                "prev_hash": r["prev_hash"],
                "record_hash": r["record_hash"],
            })
        return out
