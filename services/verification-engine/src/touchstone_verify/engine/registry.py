"""Verifier factory — builds an executable `Verifier` from a definition dict.

The control-plane stores verifier definitions as JSON. The factory turns a
definition into a ready-to-run verifier, recursively constructing ensemble
members. It is the single place that knows the mapping from ``type`` string to
implementation, so adding a new verifier family touches exactly one switch.

Dependency injection: the sandbox runner and model provider are passed in, so
the same factory is used in production (real provider) and in tests (mock),
and so the expensive sandbox runner is shared across verifiers.
"""

from __future__ import annotations

from typing import Any

from ..providers.base import ModelProvider
from ..sandbox.runner import SandboxRunner
from .base import Verifier, VerifierError
from .code_verifier import CodeVerifier
from .ensemble import EnsembleVerifier
from .model_verifier import ModelVerifier
from .process_verifier import ProcessVerifier


class VerifierFactory:
    def __init__(
        self,
        *,
        sandbox: SandboxRunner,
        provider: ModelProvider | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._provider = provider

    def build(self, definition: dict[str, Any]) -> Verifier:
        vtype = definition.get("type")
        if vtype == "code":
            return CodeVerifier(definition, runner=self._sandbox)
        if vtype == "process":
            return ProcessVerifier(definition, runner=self._sandbox)
        if vtype == "model":
            if self._provider is None:
                raise VerifierError("model verifier requires a configured provider")
            return ModelVerifier(definition, provider=self._provider)
        if vtype == "hybrid":
            members_def = definition.get("members") or []
            if not members_def:
                raise VerifierError("hybrid verifier requires 'members'")
            members = [self.build(m) for m in members_def]
            return EnsembleVerifier(
                members,
                weights=definition.get("weights"),
                threshold=float(definition.get("threshold", 0.5)),
                escalate_uncertainty=float(definition.get("escalate_uncertainty", 0.3)),
            )
        raise VerifierError(f"unknown verifier type: {vtype!r}")
