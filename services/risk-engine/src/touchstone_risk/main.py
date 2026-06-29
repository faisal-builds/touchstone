"""Risk-engine entrypoint. Run with: python -m touchstone_risk.main"""

from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from .config import get_settings
from .observability.logging import configure_logging
from .publisher import KafkaPublisher
from .repository import Repository
from .scorer import RiskModel
from .worker import Worker

log = structlog.get_logger(__name__)


async def _amain() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    publisher = KafkaPublisher(settings.redpanda_brokers)
    await publisher.start()
    worker = Worker(repository=Repository(engine), publisher=publisher, model=RiskModel())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    task = asyncio.create_task(
        worker.run(settings.redpanda_brokers, settings.consumer_group,
                   max_concurrency=settings.max_concurrency)
    )
    log.info("risk_engine.started", env=settings.environment.value)
    await stop.wait()
    task.cancel()
    await publisher.stop()
    await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
