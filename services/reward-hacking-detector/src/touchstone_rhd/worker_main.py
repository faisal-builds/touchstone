"""Worker entrypoint — auto-evaluates verifiers on registration.

Run with: python -m touchstone_rhd.worker_main
"""

from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy.ext.asyncio import create_async_engine
from touchstone_verify.sandbox.base import build_sandbox

from .config import get_settings
from .knowledge.repository import KnowledgeBase
from .observability.logging import configure_logging
from .orchestrator import EvaluationConfig, Orchestrator
from .publisher import KafkaPublisher
from .worker import AutoEvaluateWorker, EvaluationJobRunner

log = structlog.get_logger(__name__)


async def _amain() -> None:
    settings = get_settings()
    configure_logging(settings)
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    publisher = KafkaPublisher(settings.redpanda_brokers)
    await publisher.start()
    sandbox = build_sandbox(
        settings.sandbox_backend,
        image=settings.sandbox_image,
        allow_fallback=settings.sandbox_allow_fallback,
    )
    runner = EvaluationJobRunner(
        kb=KnowledgeBase(engine), orchestrator=Orchestrator(sandbox=sandbox), publisher=publisher,
        max_retries=settings.max_retries, retry_backoff_s=settings.retry_backoff_s,
    )
    config = EvaluationConfig(
        seed=settings.default_seed, max_attacks=settings.max_attacks,
        max_concurrency=settings.max_concurrency,
        per_attack_timeout_s=settings.per_attack_timeout_s,
        enable_model_attacks=settings.enable_model_attacks,
    )
    worker = AutoEvaluateWorker(runner=runner, config=config)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    task = asyncio.create_task(
        worker.run(settings.redpanda_brokers, settings.consumer_group)
    )
    log.info("rhd_worker.started", auto=settings.auto_evaluate_on_register)
    await stop.wait()
    task.cancel()
    await publisher.stop()
    await engine.dispose()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
