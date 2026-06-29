# syntax=docker/dockerfile:1.7
# risk-engine worker image — runs a Redpanda consumer loop, no HTTP port.
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY libs/touchstone-events /build/libs/touchstone-events
COPY services/risk-engine/pyproject.toml /build/services/risk-engine/pyproject.toml
COPY services/risk-engine/src /build/services/risk-engine/src
RUN pip install /build/libs/touchstone-events && pip install /build/services/risk-engine

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system touchstone && useradd --system --gid touchstone --uid 10003 touchstone
COPY --from=builder /opt/venv /opt/venv
COPY services/risk-engine/src /app/src
ENV PYTHONPATH=/app/src
USER touchstone
CMD ["python", "-m", "touchstone_risk.main"]
