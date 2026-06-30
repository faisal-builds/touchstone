# syntax=docker/dockerfile:1.7
# Multi-stage build for the Touchstone control-plane.
#  * builder: installs deps into a venv
#  * runtime: slim, non-root, only the venv + source
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

# Build deps for asyncpg/argon2 native wheels.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the shared events lib then the service. Copy manifests first for layer
# caching, then source.
COPY libs/touchstone-events /build/libs/touchstone-events
COPY services/control-plane/pyproject.toml /build/services/control-plane/pyproject.toml
COPY services/control-plane/src /build/services/control-plane/src
RUN pip install /build/libs/touchstone-events \
    && pip install /build/services/control-plane

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Create an unprivileged user; containers must never run as root in production.
RUN groupadd --system touchstone && useradd --system --gid touchstone --uid 10001 touchstone

COPY --from=builder /opt/venv /opt/venv
COPY services/control-plane/src /app/src
COPY services/control-plane/alembic.ini /app/alembic.ini

ENV PYTHONPATH=/app/src
USER touchstone
EXPOSE 8000

# Liveness probe (the slim image has no curl/wget; use the interpreter). Mirrors
# the k8s liveness probe so `docker run`/compose see the same health signal.
# start-period covers alembic migrations before gunicorn binds.
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status==200 else 1)"]

# gunicorn manages uvicorn workers. Worker count is overridden per-pod via env.
# Graceful timeout gives in-flight verifications time to finish on rollout.
CMD ["gunicorn", "touchstone_control.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
