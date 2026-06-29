"""Verification-engine entrypoint.

Run with: ``python -m touchstone_verify.main``

Wires the real dependency graph (DB engine, artifact store, sandbox, model
provider, Kafka publisher) and starts the consumer loop. Model provider selection
is automatic: the real Anthropic provider when an API key is configured,
otherwise the deterministic mock (so the engine boots and runs in any environment).
"""

from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from .artifact_store import ArtifactStore
from .config import Settings, get_settings
from .engine.registry import VerifierFactory
from .observability.logging import configure_logging
from .providers.anthropic import AnthropicProvider
from .providers.base import ModelProvider
from .providers.mock import MockProvider
from .publisher import KafkaPublisher
from .repository import Repository
from .sandbox.base import build_sandbox
from .worker import Worker

log = structlog.get_logger(__name__)


def _select_provider(settings: Settings) -> ModelProvider:
    if settings.anthropic_api_key is not None:
        log.info("provider.anthropic")
        return AnthropicProvider(settings.anthropic_api_key.get_secret_value())
    log.info("provider.mock", reason="no api key configured")
    return MockProvider()


async def _amain() -> None:
    settings = get_settings()
    configure_logging(settings)

    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    repository = Repository(engine)
    artifacts = ArtifactStore(settings.artifact_store_uri)
    sandbox = build_sandbox(
        settings.sandbox_backend,
        image=settings.sandbox_image,
        allow_fallback=settings.sandbox_allow_fallback,
    )
    provider = _select_provider(settings)
    factory = VerifierFactory(sandbox=sandbox, provider=provider)

    publisher = KafkaPublisher(settings.redpanda_brokers)
    await publisher.start()

    worker = Worker(
        repository=repository,
        factory=factory,
        artifacts=artifacts,
        publisher=publisher,
        default_timeout_s=settings.default_timeout_s,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    consume = asyncio.create_task(
        worker.run(
            settings.redpanda_brokers,
            settings.consumer_group,
            max_concurrency=settings.max_concurrency,
        )
    )
    log.info("verification_engine.started", env=settings.environment.value)
    await stop.wait()
    log.info("verification_engine.stopping")
    consume.cancel()
    await publisher.stop()
    await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
