"""Chaos engineering framework — failpoints + scenarios.

The mechanism behind controlled fault injection: systems declare named
**failpoints** at the places where reality bites (sandbox execution, region
routing, the event bus), and a :class:`FaultInjector` can *arm* those points with
latency, errors, or hard drops — probabilistically — at runtime. A
:class:`ChaosScenario` scripts a sequence of arm/disarm steps so a test (or a
live game-day) can drive the system through a fault and assert it degrades the way
it should (fail-open/closed, spill, shed) instead of cascading.

This is the framework. The *findings* — which faults actually hurt, the real blast
radius, the surprising correlations — only come from running it against live
production traffic. The framework makes those experiments possible; it does not
substitute for having run them.
"""

from __future__ import annotations

import dataclasses
import random


class InjectedFault(RuntimeError):
    """Raised at a failpoint that is armed to error."""


@dataclasses.dataclass
class Fault:
    name: str
    probability: float = 1.0          # 0..1 chance of firing per hit
    latency_s: float = 0.0            # added delay when it fires
    error: bool = False               # raise InjectedFault when it fires
    drop: bool = False                # signal the caller to drop/shed
    max_fires: int | None = None      # auto-disarm after N fires (None = unlimited)
    fires: int = 0


class FaultInjector:
    """Holds armed faults and is consulted at failpoints.

    When no fault is armed for a name, every method is a cheap no-op, so leaving
    failpoints in the hot path costs effectively nothing in normal operation.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self._faults: dict[str, Fault] = {}
        self._rng = rng or random.Random()

    def arm(self, name: str, *, probability: float = 1.0, latency_s: float = 0.0,
            error: bool = False, drop: bool = False, max_fires: int | None = None) -> None:
        self._faults[name] = Fault(
            name=name, probability=probability, latency_s=latency_s, error=error,
            drop=drop, max_fires=max_fires,
        )

    def disarm(self, name: str) -> None:
        self._faults.pop(name, None)

    def clear(self) -> None:
        self._faults.clear()

    def armed(self, name: str) -> bool:
        return name in self._faults

    def _should_fire(self, fault: Fault) -> bool:
        if fault.max_fires is not None and fault.fires >= fault.max_fires:
            self.disarm(fault.name)
            return False
        if fault.probability >= 1.0:
            fire = True
        else:
            fire = self._rng.random() < fault.probability
        if fire:
            fault.fires += 1
            if fault.max_fires is not None and fault.fires >= fault.max_fires:
                self.disarm(fault.name)
        return fire

    def latency(self, name: str) -> float:
        """Return the delay (seconds) to apply at this failpoint, else 0.0."""
        fault = self._faults.get(name)
        if fault is None or not fault.latency_s:
            return 0.0
        return fault.latency_s if self._should_fire(fault) else 0.0

    def should_drop(self, name: str) -> bool:
        fault = self._faults.get(name)
        if fault is None or not fault.drop:
            return False
        return self._should_fire(fault)

    def failpoint(self, name: str) -> None:
        """Raise :class:`InjectedFault` if an error fault is armed and fires."""
        fault = self._faults.get(name)
        if fault is None or not fault.error:
            return
        if self._should_fire(fault):
            raise InjectedFault(f"chaos failpoint '{name}' fired")


@dataclasses.dataclass
class ChaosStep:
    label: str
    arm: dict | None = None           # kwargs for injector.arm(name, **arm) — needs 'name'
    disarm: str | None = None         # name to disarm


class ChaosScenario:
    """A scripted sequence of fault arm/disarm steps."""

    def __init__(self, name: str, steps: list[ChaosStep]) -> None:
        self.name = name
        self.steps = steps


class ChaosRunner:
    """Applies a scenario step-by-step against a shared injector, running a probe
    callable after each step and collecting results. Always disarms on exit."""

    def __init__(self, injector: FaultInjector) -> None:
        self._injector = injector

    async def run(self, scenario: ChaosScenario, probe) -> list[tuple[str, object]]:
        results: list[tuple[str, object]] = []
        try:
            for step in scenario.steps:
                if step.arm is not None:
                    spec = dict(step.arm)
                    self._injector.arm(spec.pop("name"), **spec)
                if step.disarm is not None:
                    self._injector.disarm(step.disarm)
                results.append((step.label, await probe()))
        finally:
            self._injector.clear()
        return results
