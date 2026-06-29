# Architecture Decision Records

Frozen decisions for Touchstone V1. Changing any of these requires a new ADR
that supersedes the prior one — never edit a frozen decision in place.

| #   | Decision            | Choice |
|-----|---------------------|--------|
| 001 | Repo topology       | Monorepo (uv workspaces + Turborepo for web) |
| 002 | Service runtime     | Python 3.12 / FastAPI; isolated sandbox for code-verifiers |
| 003 | Concurrency         | Async everywhere (SQLAlchemy 2.0 async, asyncpg, httpx) |
| 004 | Primary datastore   | PostgreSQL 16 |
| 005 | Audit/event store   | ClickHouse (events) + S3 (raw trajectories) |
| 006 | Event backbone      | Redpanda (Kafka API) |
| 007 | Cache/ratelimit     | Redis 7 |
| 008 | Service boundaries  | control-plane, verification-engine, risk-engine, audit-engine, reward-hacking-detector, web, sdks |
| 009 | AuthN               | API keys (Argon2id) + JWT/OIDC |
| 010 | AuthZ               | RBAC scoped org → workspace → project |
| 011 | Audit integrity     | Hash-chained append-only per-org Merkle chain |
| 012 | Infra               | Docker → Kubernetes (Helm) → AWS (Terraform); GitHub Actions |
| 013 | Observability       | OpenTelemetry → Prometheus/Grafana/Tempo; structlog; Sentry |
| 014 | Contracts           | OpenAPI 3.1 from code; SDKs generated from it |
| 015 | Inline plane        | Inline Verification Plane (IVP) — synchronous allow/block/redact/escalate on live traffic; see [015](015-inline-verification-plane.md) |
| 016 | Enterprise fleet    | `touchstone-fleet` primitives (global control plane, policy distribution, region routing/failover, scheduler, chaos, SLO, capacity) + region-aware IVP; see [016](016-enterprise-evolution-milestone-1.md). **Mechanisms, not production-proven.** |
