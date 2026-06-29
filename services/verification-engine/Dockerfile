# syntax=docker/dockerfile:1.7
# Verification-engine worker image. Runs the Redpanda consumer loop, not an HTTP
# server, so there is no exposed port — it is a background Deployment in k8s.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY libs/touchstone-events /build/libs/touchstone-events
COPY services/verification-engine/pyproject.toml /build/services/verification-engine/pyproject.toml
COPY services/verification-engine/src /build/services/verification-engine/src
RUN pip install /build/libs/touchstone-events \
    && pip install "/build/services/verification-engine[s3]"

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# 'unshare' (util-linux) is used by the sandbox for network isolation.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system touchstone && useradd --system --gid touchstone --uid 10002 touchstone
COPY --from=builder /opt/venv /opt/venv
COPY services/verification-engine/src /app/src
ENV PYTHONPATH=/app/src
USER touchstone

# The worker is its own supervisor; k8s restarts it on exit.
CMD ["python", "-m", "touchstone_verify.main"]
