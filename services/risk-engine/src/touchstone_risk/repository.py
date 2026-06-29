"""Risk-engine data access (SQLAlchemy Core, decoupled from the control-plane ORM).

Writes the computed ``risk_score`` back onto the verification run. The band and
contributing factors travel on the emitted ``risk.scored`` event (the run table
stores the scalar score; richer risk analytics live in the event stream / future
risk store).
"""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import Column, DateTime, Float, MetaData, Table, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncEngine

_metadata = MetaData()

verification_runs = Table(
    "verification_runs", _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("risk_score", Float),
    Column("updated_at", DateTime(timezone=True)),
)


class Repository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def set_risk_score(self, run_id: uuid.UUID, risk_score: float) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(verification_runs)
                .where(verification_runs.c.id == run_id)
                .values(
                    risk_score=risk_score,
                    updated_at=_dt.datetime.now(_dt.UTC),
                )
            )
