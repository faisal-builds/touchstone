"""Model provider seam.

The reward-hacking detector reuses the verification-engine's provider
abstraction (and its mock + Anthropic implementations) rather than defining its
own, so an LLM-as-attacker and an LLM-as-judge share one client surface. This
module is the single import point for the rest of the package.
"""

from __future__ import annotations

from touchstone_verify.providers.base import JudgeRequest, JudgeResponse, ModelProvider
from touchstone_verify.providers.mock import MockProvider

__all__ = ["ModelProvider", "JudgeRequest", "JudgeResponse", "MockProvider"]
