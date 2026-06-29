"""Data access for the verification-engine.

The engine deliberately uses SQLAlchemy **Core** (not the control-plane's ORM)
with a minimal reflective view of the two tables it touches: it *reads* verifier
definitions and *writes* run results. This keeps the engine decoupled from the
control-plane's models (service independence) while sharing the physical
database in V1. A future split to per-service databases changes only this file.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncEngine

_metadata = MetaData()

# Native PG enum for status. create_type=False: the control-plane migration owns
# the type; we only reference it so Core binds values as the enum, not VARCHAR.
_verification_status = ENUM(
    "pending", "running", "completed", "failed",
    name="verification_status", create_type=False,
)

# Minimal column views — only what the engine reads/writes. These mirror the
# control-plane schema by name; they are not the authoritative definition.
verifiers = Table(
    "verifiers", _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("project_id", UUID(as_uuid=True)),
    Column("verifier_type", String),
    Column("definition", JSONB),
    Column("robustness_score", Float),
)

verification_runs = Table(
    "verification_runs", _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("status", _verification_status),
    Column("score", Float),
    Column("uncertainty", Float),
    Column("passed", Boolean),
    Column("grader_breakdown", JSON),
    Column("latency_ms", Integer),
    Column("error", Text),
    Column("updated_at", DateTime(timezone=True)),
)


@dataclass(frozen=True)
class VerifierRecord:
    id: uuid.UUID
    organization_id: uuid.UUID
    verifier_type: str
    definition: dict[str, Any]


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_verifier(self, verifier_id: uuid.UUID) -> VerifierRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(
                        verifiers.c.id,
                        verifiers.c.organization_id,
                        verifiers.c.verifier_type,
                        verifiers.c.definition,
                    ).where(verifiers.c.id == verifier_id)
                )
            ).first()
        if row is None:
            return None
        definition = dict(row.definition or {})
        # Ensure the definition carries its type for the factory.
        definition.setdefault("type", row.verifier_type)
        return VerifierRecord(
            id=row.id,
            organization_id=row.organization_id,
            verifier_type=row.verifier_type,
            definition=definition,
        )

    async def mark_running(self, run_id: uuid.UUID) -> None:
        await self._update(run_id, {"status": "running"})

    async def mark_completed(
        self,
        run_id: uuid.UUID,
        *,
        score: float,
        uncertainty: float,
        passed: bool,
        breakdown: dict[str, float],
        latency_ms: int,
    ) -> None:
        await self._update(
            run_id,
            {
                "status": "completed",
                "score": score,
                "uncertainty": uncertainty,
                "passed": passed,
                "grader_breakdown": breakdown,
                "latency_ms": latency_ms,
                "error": None,
            },
        )

    async def mark_failed(self, run_id: uuid.UUID, error: str, latency_ms: int) -> None:
        await self._update(
            run_id,
            {"status": "failed", "error": error[:4000], "latency_ms": latency_ms},
        )

    async def _update(self, run_id: uuid.UUID, values: dict[str, Any]) -> None:
        values["updated_at"] = _dt.datetime.now(_dt.UTC)
        async with self._engine.begin() as conn:
            await conn.execute(
                update(verification_runs)
                .where(verification_runs.c.id == run_id)
                .values(**values)
            )
