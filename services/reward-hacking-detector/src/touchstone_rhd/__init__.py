"""Touchstone Reward-Hacking Detector.

Measures how robust an AI *verifier* is against manipulation by generating diverse
adversarial artifacts, running them through the verifier (reusing the
verification-engine's hardened execution), detecting reward hacks (undeserving
artifacts the verifier passes), and scoring robustness with a confidence interval.
"""

from ._version import __version__

__all__ = ["__version__"]
