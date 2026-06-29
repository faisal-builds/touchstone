"""Evaluation orchestrator.

Runs one complete robustness evaluation end to end and returns an
``EvaluationResult``. It is intentionally **pure** with respect to storage — it
takes a verifier definition and seed cases and produces a result object — so it
can be unit/integration tested without a database. Persistence (lifecycle rows,
exploit corpus, robustness writeback) is the worker's responsibility.

Pipeline:
    seed cases ─▶ AttackGenerator (reproducible variants)
              ─▶ AttackExecutor (run through the verifier, via the engine sandbox)
              ─▶ ExploitDetector (which passes were reward hacks; categorize+dedup)
              ─▶ RobustnessScorer (robustness + Wilson CI)

Robustness is measured over *executed* (non-errored) attacks: an attack that
made the verifier crash is recorded as an error, not counted as resisted or
exploited, so it cannot inflate or deflate the score.
"""

from __future__ import annotations

import dataclasses

import structlog
from touchstone_verify.engine.registry import VerifierFactory
from touchstone_verify.sandbox.base import Sandbox
from touchstone_verify.sandbox.runner import SandboxRunner

from .attacks.generator import AttackGenerator, default_strategies
from .detection.detector import ExploitDetector
from .domain.models import AttackCase, EvaluationResult
from .providers import MockProvider, ModelProvider
from .scoring.robustness import RobustnessScorer

log = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class EvaluationConfig:
    seed: int = 1337
    max_attacks: int | None = 2000
    max_concurrency: int = 16
    per_attack_timeout_s: float = 15.0
    enable_model_attacks: bool = False


class Orchestrator:
    def __init__(
        self,
        *,
        sandbox: Sandbox | None = None,
        provider: ModelProvider | None = None,
        detector: ExploitDetector | None = None,
        scorer: RobustnessScorer | None = None,
    ) -> None:
        # Any Sandbox backend works (subprocess baseline or gVisor/Firecracker);
        # production injects the configured hardened backend. The no-arg default
        # keeps the subprocess baseline for tests and local runs.
        self._sandbox = sandbox or SandboxRunner()
        self._provider = provider
        self._detector = detector or ExploitDetector()
        self._scorer = scorer or RobustnessScorer()

    async def evaluate(
        self,
        *,
        verifier_definition: dict,
        seed_cases: list[AttackCase],
        config: EvaluationConfig,
        evaluation_id: str,
    ) -> EvaluationResult:
        # A provider is needed both for model verifiers and model-generated
        # attacks; default to the deterministic mock so evaluations are offline
        # and reproducible unless a real provider is injected.
        provider = self._provider or MockProvider()

        factory = VerifierFactory(sandbox=self._sandbox, provider=provider)
        verifier = factory.build(verifier_definition)

        generator = AttackGenerator(
            default_strategies(include_model=config.enable_model_attacks),
            verifier_definition=verifier_definition,
            provider=provider if config.enable_model_attacks else None,
        )
        variants = await generator.generate(
            seed=config.seed, cases=seed_cases, max_attacks=config.max_attacks
        )

        from .execution.executor import AttackExecutor

        executor = AttackExecutor(
            max_concurrency=config.max_concurrency,
            per_attack_timeout_s=config.per_attack_timeout_s,
        )
        outcomes = await executor.execute(verifier, variants, evaluation_id=evaluation_id)

        errored = sum(1 for o in outcomes if o.errored)
        executed = len(outcomes) - errored
        exploits = self._detector.detect(outcomes)
        score = self._scorer.score(executed=executed, exploits=len(exploits))
        weighted = self._scorer.weighted_score(
            executed=executed, severities=[e.severity for e in exploits]
        )

        category_counts: dict[str, int] = {}
        for ex in exploits:
            category_counts[ex.category.value] = category_counts.get(ex.category.value, 0) + 1

        log.info(
            "evaluation.complete", evaluation_id=evaluation_id,
            total=len(variants), executed=executed, errored=errored,
            exploits=len(exploits), robustness=score.robustness,
            weighted_robustness=weighted,
        )
        return EvaluationResult(
            seed=config.seed,
            total_attacks=len(variants),
            executed=executed,
            errored=errored,
            exploits=exploits,
            robustness_score=score.robustness,
            robustness_ci=score.ci,
            category_counts=category_counts,
            weighted_robustness_score=weighted,
        )
