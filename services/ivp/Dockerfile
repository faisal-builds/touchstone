# syntax=docker/dockerfile:1.7
# Inline Verification Plane (IVP) image — the inline/critical-path gateway.
# Serves the inline API (uvicorn factory). Because the fast tier executes code
# verifiers through the verification-engine sandbox, the runtime includes
# util-linux ('unshare') and, in production, runs under the gVisor runtimeClass.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# The plane reuses the verification-engine (sandbox/code verifier) and the
# risk-engine (scoring model), plus the shared event contracts and the
# fleet primitives (region-aware routing/coordination).
COPY libs/touchstone-events /build/libs/touchstone-events
COPY libs/touchstone-fleet /build/libs/touchstone-fleet
COPY services/verification-engine /build/services/verification-engine
COPY services/risk-engine /build/services/risk-engine
COPY services/ivp/pyproject.toml /build/services/ivp/pyproject.toml
COPY services/ivp/src /build/services/ivp/src
RUN pip install /build/libs/touchstone-events \
    && pip install /build/libs/touchstone-fleet \
    && pip install /build/services/verification-engine \
    && pip install /build/services/risk-engine \
    && pip install /build/services/ivp

# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# 'unshare' (util-linux) is used by the sandbox for network isolation.
RUN apt-get update && apt-get install -y --no-install-recommends util-linux \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system touchstone && useradd --system --gid touchstone --uid 10006 touchstone
COPY --from=builder /opt/venv /opt/venv
COPY services/ivp/src /app/src
COPY services/verification-engine/src /app/verification-engine-src
COPY services/risk-engine/src /app/risk-engine-src
ENV PYTHONPATH=/app/src:/app/verification-engine-src:/app/risk-engine-src
USER touchstone
EXPOSE 8050

# Liveness probe (slim image: no curl/wget; use the interpreter).
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8050/healthz', timeout=2).status==200 else 1)"]

# The inline gateway. create_app is exposed as a uvicorn factory.
CMD ["uvicorn", "touchstone_ivp.main:app", "--factory", "--host", "0.0.0.0", "--port", "8050"]
