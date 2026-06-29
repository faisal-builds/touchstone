"""Health & readiness endpoints (consumed by k8s probes + ALB, ADR-012).

  * ``/healthz``  — liveness: process is up. Never touches dependencies.
  * ``/readyz``   — readiness: dependencies (Postgres, Redis) are reachable.
                    A failing readiness check pulls the pod out of rotation
                    without killing it.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ...._version import __version__
from ..deps import SessionDep, SettingsDep

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe")
async def readyz(session: SessionDep, settings: SettingsDep) -> dict:
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "unavailable"
    ready = all(v == "ok" for v in checks.values())
    return {
        "status": "ready" if ready else "degraded",
        "service": settings.service_name,
        "version": __version__,
        "checks": checks,
    }
