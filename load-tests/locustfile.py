"""Touchstone load-test entry point (Locust).

Run via the helper scripts (``./run.sh <profile>``) or directly, e.g.:

    locust -f locustfile.py --headless -u 10 -r 2 -t 1m --host http://localhost:8000

The active profile (``TOUCHSTONE_LOAD_PROFILE``) drives both the scaling flags
(set by ``run.sh``) and the pass/fail thresholds enforced here when the run stops.
"""

from __future__ import annotations

from locust import events

from touchstone_load import metrics
from touchstone_load.config import get_profile, get_targets
from touchstone_load.users import (  # noqa: F401 — discovered by Locust
    ControlPlaneUser,
    VerificationHotPathUser,
)

_PROFILE = get_profile()
_TARGETS = get_targets()

# Attach the reward-hacking-detector scenarios only when explicitly enabled, and
# point that user at the RHD host (the control-plane host comes from --host).
if _TARGETS.enable_rhd:
    from touchstone_load.users import RobustnessUser  # noqa: F401

    RobustnessUser.host = _TARGETS.rhd_url


@events.test_start.add_listener
def _on_test_start(environment, **_kw):
    metrics.COUNTERS.reset()
    print(f"[touchstone-load] profile={_PROFILE.name} "
          f"users={_PROFILE.users} spawn_rate={_PROFILE.spawn_rate} "
          f"run_time={_PROFILE.run_time} expect_completion={_PROFILE.expect_completion}")


@events.test_stop.add_listener
def _on_test_stop(environment, **_kw):
    breaches, summary = metrics.evaluate(environment, _PROFILE)
    print("\n========== Touchstone load summary ==========")
    for line in summary:
        print("  " + line)
    if breaches:
        print("  --- THRESHOLD BREACHES ---")
        for b in breaches:
            print(f"  ! {b.metric}: observed {b.observed:.2f} > limit {b.limit:.2f}")
        environment.process_exit_code = 1
        print("  RESULT: FAIL")
    else:
        environment.process_exit_code = 0
        print("  RESULT: PASS")
    print("=============================================\n")
