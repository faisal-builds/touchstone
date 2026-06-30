"""Shared test setup for the IVP suite.

The inline plane now FAILS CLOSED: with the default ``subprocess`` backend it
refuses to run untrusted code unless the explicit insecure opt-in is set
(``TOUCHSTONE_ALLOW_INSECURE_SANDBOX``). The test suite is exactly the sanctioned
"local dev" context that opt-in exists for — integration tests run the real POSIX
subprocess sandbox — so enable it for the whole suite here.

This is set with ``setdefault`` at collection time (before any app fixture is
built) so a real environment value still wins, and tests that specifically
exercise the *refusal* path simply ``monkeypatch.delenv`` it within the test.
"""

from __future__ import annotations

import os

os.environ.setdefault("TOUCHSTONE_ALLOW_INSECURE_SANDBOX", "1")
