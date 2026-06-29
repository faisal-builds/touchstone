"""Robustness-consumer entrypoint.

Run with: python -m touchstone_control.consumer_main

Consumes ``reward_hacking.robustness_evaluated`` and applies the headline
robustness score onto the verifier row (the control-plane is the sole writer of
the ``verifiers`` table after the per-service database split).
"""

from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from .core.config import get_settings
from .observability.logging import configure_logging
from .observability.robustness_consumer import RobustnessConsumer

log = structlog.get_logger(__name__)

CONSUMER_GROUP = "control-plane-robustness"


async def _amain() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    consumer = RobustnessConsumer(engine)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    task = asyncio.create_task(consumer.run(settings.redpanda_brokers, CONSUMER_GROUP))
    log.info("control_plane.robustness_consumer.started")
    await stop.wait()
    task.cancel()
    await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
