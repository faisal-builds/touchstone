"""Touchstone Inline Verification Plane (IVP).

The IVP is the inline/critical-path tier of Touchstone: it runs verifiers on live
AI traffic and returns an allow / block / redact / escalate decision inside a
configurable latency budget, then records the decision to the audit chain. It
reuses the verification-engine's sandboxed verifier execution, the risk-engine's
scoring model, and the reward-hacking-detector's robustness scores (to route
around gameable verifiers), and integrates over the existing event bus.
"""

from ._version import __version__

__all__ = ["__version__"]
