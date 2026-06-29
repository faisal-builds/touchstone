"""Knowledge base — persistence for evaluations and the exploit corpus.

This is the platform's growing record of *how verifiers fail*. Every confirmed
exploit is stored; re-discovering the same exploit (same verifier + signature)
increments its occurrence count and recency rather than duplicating it, so the
corpus accumulates distinct failure modes over time.

The repository also writes the headline ``robustness_score`` back onto the
verifier row (so the rest of the platform — registry, SDK, dashboards — sees it)
and exposes the history needed for trends, version comparison, and regression
detection.

SQLAlchemy Core only; no dependency on the control-plane ORM. Adversarial
artifacts are stored as ASCII-escaped JSON (``artifact_json``) so hostile inputs
(null bytes, control chars) round-trip safely.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ..domain.models import EvaluationResult

_md = MetaData()

# Public alias + helpers: RHD owns and creates its own schema (single-writer).
metadata = _md


async def create_schema(engine: AsyncEngine) -> None:
    """Create RHD's own tables (evaluations, exploits, verifier_refs)."""
    async with engine.begin() as c:
        await c.run_sync(_md.create_all)


async def drop_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.run_sync(_md.drop_all)

evaluations = Table(
    "robustness_evaluations", _md,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("verifier_id", UUID(as_uuid=True)),
    Column("verifier_version", Integer),
    Column("status", String),
    Column("seed", BigInteger),
    Column("total_attacks", Integer),
    Column("executed", Integer),
    Column("errored", Integer),
    Column("exploits_found", Integer),
    Column("robustness_score", Float),
    Column("weighted_robustness_score", Float),
    Column("ci_low", Float),
    Column("ci_high", Float),
    Column("config", JSONB),
    Column("error", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Index("ix_robustness_eval_org", "organization_id"),
    Index("ix_robustness_eval_verifier", "verifier_id", "created_at"),
)

exploits = Table(
    "exploits", _md,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("verifier_id", UUID(as_uuid=True)),
    Column("evaluation_id", UUID(as_uuid=True)),
    Column("first_seen_evaluation_id", UUID(as_uuid=True)),
    Column("signature", String),
    Column("verifier_version", Integer),
    Column("category", String),
    Column("strategy", String),
    Column("severity", String),
    Column("artifact_json", Text),
    Column("verifier_score", Float),
    Column("description", Text),
    Column("failure_reason", Text),
    Column("occurrences", Integer),
    Column("last_seen_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("verifier_id", "signature", name="uq_exploit_verifier_sig"),
    Index("ix_exploit_evaluation", "evaluation_id"),
    Index("ix_exploit_org", "organization_id"),
    Index("ix_exploit_verifier", "verifier_id"),
)

# RHD's own read-model replica of the minimal verifier facts it needs to run an
# evaluation. Populated from the control-plane's `verifier.registered` event (see
# the auto-evaluate consumer), so RHD never reads the control-plane database.
verifier_refs = Table(
    "verifier_refs", _md,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("organization_id", UUID(as_uuid=True)),
    Column("version", Integer),
    Column("verifier_type", String),
    Column("definition", JSONB),
    Column("updated_at", DateTime(timezone=True)),
)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _dump(artifact: Any) -> str:
    return json.dumps(artifact, ensure_ascii=True, default=str)


@dataclasses.dataclass(frozen=True, slots=True)
class VerifierInfo:
    id: uuid.UUID
    organization_id: uuid.UUID
    version: int
    definition: dict


class KnowledgeBase:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # --- verifier lookup ------------------------------------------------------
    # --- verifier replica (read model) ---------------------------------------
    async def upsert_verifier_ref(
        self, *, verifier_id: uuid.UUID, organization_id: uuid.UUID,
        version: int, verifier_type: str, definition: dict,
    ) -> None:
        """Upsert the local verifier replica from a `verifier.registered` event.

        This is RHD's single source of truth for verifier facts; the
        control-plane database is never read.
        """
        now = _now()
        stmt = insert(verifier_refs).values(
            id=verifier_id, organization_id=organization_id, version=version,
            verifier_type=verifier_type, definition=definition, updated_at=now,
        )
        async with self._engine.begin() as c:
            await c.execute(stmt.on_conflict_do_update(
                index_elements=[verifier_refs.c.id],
                set_={
                    "organization_id": organization_id, "version": version,
                    "verifier_type": verifier_type, "definition": definition,
                    "updated_at": now,
                },
            ))

    async def get_verifier(self, verifier_id: uuid.UUID) -> VerifierInfo | None:
        async with self._engine.connect() as c:
            row = (await c.execute(
                select(verifier_refs.c.id, verifier_refs.c.organization_id,
                       verifier_refs.c.version, verifier_refs.c.verifier_type,
                       verifier_refs.c.definition)
                .where(verifier_refs.c.id == verifier_id)
            )).first()
        if row is None:
            return None
        # The engine factory keys off definition["type"]; the column is the source
        # of truth, so inject it (definitions in storage may omit it).
        definition = dict(row.definition or {})
        definition.setdefault("type", row.verifier_type)
        return VerifierInfo(row.id, row.organization_id, row.version, definition)

    # --- evaluation lifecycle -------------------------------------------------
    async def create_evaluation(
        self, *, organization_id: uuid.UUID, verifier_id: uuid.UUID,
        verifier_version: int, seed: int, config: dict,
    ) -> uuid.UUID:
        eval_id = uuid.uuid4()
        now = _now()
        async with self._engine.begin() as c:
            await c.execute(evaluations.insert().values(
                id=eval_id, organization_id=organization_id, verifier_id=verifier_id,
                verifier_version=verifier_version, status="pending", seed=seed,
                total_attacks=0, executed=0, errored=0, exploits_found=0,
                config=config, created_at=now, updated_at=now,
            ))
        return eval_id

    async def mark_running(self, eval_id: uuid.UUID) -> None:
        async with self._engine.begin() as c:
            await c.execute(update(evaluations).where(evaluations.c.id == eval_id)
                            .values(status="running", started_at=_now(), updated_at=_now()))

    async def fail_evaluation(self, eval_id: uuid.UUID, error: str) -> None:
        async with self._engine.begin() as c:
            await c.execute(update(evaluations).where(evaluations.c.id == eval_id)
                            .values(status="failed", error=error[:2000],
                                    completed_at=_now(), updated_at=_now()))

    async def complete_evaluation(
        self, eval_id: uuid.UUID, *, verifier_id: uuid.UUID,
        organization_id: uuid.UUID, result: EvaluationResult,
        verifier_version: int = 0,
    ) -> None:
        """Persist results: update the evaluation row, upsert exploits into the
        corpus (dedup per verifier), and write robustness back onto the verifier."""
        now = _now()
        async with self._engine.begin() as c:
            await c.execute(update(evaluations).where(evaluations.c.id == eval_id).values(
                status="completed", total_attacks=result.total_attacks,
                executed=result.executed, errored=result.errored,
                exploits_found=result.exploits_found,
                robustness_score=result.robustness_score,
                weighted_robustness_score=result.weighted_robustness_score,
                ci_low=result.robustness_ci.low, ci_high=result.robustness_ci.high,
                completed_at=now, updated_at=now,
            ))
            for ex in result.exploits:
                stmt = insert(exploits).values(
                    id=uuid.uuid4(), organization_id=organization_id,
                    verifier_id=verifier_id, verifier_version=verifier_version,
                    evaluation_id=eval_id,
                    first_seen_evaluation_id=eval_id, signature=ex.signature,
                    category=ex.category.value, strategy=ex.strategy,
                    severity=ex.severity.value, artifact_json=_dump(ex.artifact),
                    verifier_score=ex.verifier_score, description=ex.description,
                    failure_reason=ex.failure_reason,
                    occurrences=1, last_seen_at=now, created_at=now, updated_at=now,
                )
                # Dedup: same (verifier, signature) bumps occurrences + recency.
                await c.execute(stmt.on_conflict_do_update(
                    constraint="uq_exploit_verifier_sig",
                    set_={
                        "occurrences": exploits.c.occurrences + 1,
                        "last_seen_at": now, "evaluation_id": eval_id,
                        "verifier_version": verifier_version,
                        "severity": ex.severity.value,
                        "failure_reason": ex.failure_reason,
                        "verifier_score": ex.verifier_score, "updated_at": now,
                    },
                ))
            # NOTE: the headline robustness_score is NOT written back to the
            # control-plane's verifier row here — RHD does not write another
            # service's tables. The worker emits `reward_hacking.robustness_evaluated`
            # and the control-plane (sole writer of `verifiers`) consumes it.

    # --- queries --------------------------------------------------------------
    async def get_evaluation(self, eval_id: uuid.UUID) -> dict | None:
        async with self._engine.connect() as c:
            row = (await c.execute(
                select(evaluations).where(evaluations.c.id == eval_id)
            )).mappings().first()
        return dict(row) if row else None

    async def list_evaluations(
        self, verifier_id: uuid.UUID, *, limit: int = 50
    ) -> list[dict]:
        async with self._engine.connect() as c:
            rows = (await c.execute(
                select(evaluations).where(evaluations.c.verifier_id == verifier_id)
                .order_by(evaluations.c.created_at.desc()).limit(limit)
            )).mappings().all()
        return [dict(r) for r in rows]

    async def latest_completed_for_version(
        self, verifier_id: uuid.UUID, version: int
    ) -> dict | None:
        async with self._engine.connect() as c:
            row = (await c.execute(
                select(evaluations).where(
                    evaluations.c.verifier_id == verifier_id,
                    evaluations.c.verifier_version == version,
                    evaluations.c.status == "completed",
                ).order_by(evaluations.c.completed_at.desc()).limit(1)
            )).mappings().first()
        return dict(row) if row else None

    async def history(self, verifier_id: uuid.UUID) -> list[dict]:
        """Completed evaluations oldest→newest (for trend/regression analysis)."""
        async with self._engine.connect() as c:
            rows = (await c.execute(
                select(evaluations.c.verifier_version, evaluations.c.robustness_score,
                       evaluations.c.completed_at)
                .where(evaluations.c.verifier_id == verifier_id,
                       evaluations.c.status == "completed")
                .order_by(evaluations.c.completed_at.asc())
            )).mappings().all()
        return [dict(r) for r in rows]

    async def list_exploits(
        self, verifier_id: uuid.UUID, *, limit: int = 200
    ) -> list[dict]:
        async with self._engine.connect() as c:
            rows = (await c.execute(
                select(exploits).where(exploits.c.verifier_id == verifier_id)
                .order_by(exploits.c.last_seen_at.desc()).limit(limit)
            )).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["artifact"] = json.loads(d.pop("artifact_json"))
            out.append(d)
        return out

    async def search_exploits(
        self,
        organization_id: uuid.UUID,
        *,
        verifier_id: uuid.UUID | None = None,
        verifier_version: int | None = None,
        category: str | None = None,
        severity: str | None = None,
        strategy: str | None = None,
        min_score: float | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Search the organization's exploit corpus.

        Always scoped to the caller's organization (tenant isolation). Optional
        filters narrow by verifier, verifier version, category, severity, strategy,
        and a minimum verifier score; ``query`` is a case-insensitive substring
        match over the description, failure reason, strategy, category, and the
        stored artifact. Results are newest-first and pageable.
        """
        stmt = select(exploits).where(exploits.c.organization_id == organization_id)
        if verifier_id is not None:
            stmt = stmt.where(exploits.c.verifier_id == verifier_id)
        if verifier_version is not None:
            stmt = stmt.where(exploits.c.verifier_version == verifier_version)
        if category is not None:
            stmt = stmt.where(exploits.c.category == category)
        if severity is not None:
            stmt = stmt.where(exploits.c.severity == severity)
        if strategy is not None:
            stmt = stmt.where(exploits.c.strategy == strategy)
        if min_score is not None:
            stmt = stmt.where(exploits.c.verifier_score >= min_score)
        if query:
            like = f"%{query.lower()}%"
            stmt = stmt.where(
                func.lower(exploits.c.description).like(like)
                | func.lower(exploits.c.failure_reason).like(like)
                | func.lower(exploits.c.strategy).like(like)
                | func.lower(exploits.c.category).like(like)
                | func.lower(exploits.c.artifact_json).like(like)
            )
        stmt = stmt.order_by(exploits.c.last_seen_at.desc()).limit(limit).offset(offset)
        async with self._engine.connect() as c:
            rows = (await c.execute(stmt)).mappings().all()
        out = []
        for r in rows:
            d = dict(r)
            d["artifact"] = json.loads(d.pop("artifact_json"))
            out.append(d)
        return out

    async def list_incomplete_evaluations(self, *, limit: int = 100) -> list[dict]:
        """Evaluations stranded in pending/running (e.g. by a worker crash)."""
        async with self._engine.connect() as c:
            rows = (await c.execute(
                select(evaluations.c.id, evaluations.c.verifier_id,
                       evaluations.c.seed, evaluations.c.config,
                       evaluations.c.status)
                .where(evaluations.c.status.in_(("pending", "running")))
                .order_by(evaluations.c.created_at.asc()).limit(limit)
            )).mappings().all()
        return [dict(r) for r in rows]

    async def corpus_size(self, organization_id: uuid.UUID) -> int:
        async with self._engine.connect() as c:
            n = (await c.execute(
                select(func.count()).select_from(exploits)
                .where(exploits.c.organization_id == organization_id)
            )).scalar()
        return int(n or 0)
