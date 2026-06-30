# syntax=docker/dockerfile:1.7
# Reward-hacking-detector image. Serves the robustness API by default and can be
# run as the auto-evaluation worker by overriding the command. Because it
# executes code verifiers through the verification-engine sandbox, the runtime
# includes util-linux ('unshare') and the container needs CAP_SYS_ADMIN.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# The detector reuses the verification-engine for execution, so both that service
# and the shared event contracts are installed into the image.
COPY libs/touchstone-events /build/libs/touchstone-events
COPY services/verification-engine /build/services/verification-engine
COPY services/reward-hacking-detector/pyproject.toml /build/services/reward-hacking-detector/pyproject.toml
COPY services/reward-hacking-detector/src /build/services/reward-hacking-detector/src
RUN pip install /build/libs/touchstone-events \
    && pip install /build/services/verification-engine \
    && pip install /build/services/reward-hacking-detector

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# 'unshare' (util-linux) is used by the sandbox for network isolation.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system touchstone && useradd --system --gid touchstone --uid 10005 touchstone
COPY --from=builder /opt/venv /opt/venv
COPY services/reward-hacking-detector/src /app/src
COPY services/reward-hacking-detector/alembic.ini /app/alembic.ini
COPY services/verification-engine/src /app/verification-engine-src
ENV PYTHONPATH=/app/src:/app/verification-engine-src
USER touchstone
EXPOSE 8030

# Liveness probe (slim image: no curl/wget). The worker variant overrides the
# command and has no HTTP port, so its compose service omits this check.
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8030/healthz', timeout=2).status==200 else 1)"]

# Default: the HTTP API. The worker service overrides this with
# `python -m touchstone_rhd.worker_main`.
CMD ["python", "-m", "touchstone_rhd.main"]
