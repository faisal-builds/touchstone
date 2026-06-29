"""Custom metrics and pass/fail threshold evaluation for the load suite.

Locust already records RPS and p50/p95/p99 latency per endpoint. This module adds
the verification hot-path metrics that Locust cannot infer on its own — end-to-end
completion time and the poll-timeout rate — and evaluates the active profile's
thresholds when the run stops, setting a non-zero exit code on breach so CI fails.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Profile

# Stable stat names so reports and thresholds line up.
COMPLETION_METRIC = "verification:completed"
HOTPATH_TYPE = "HOTPATH"


@dataclass
class HotPathCounters:
    """Process-wide counters for the verification hot path.

    Locust runs greenlets cooperatively in a single OS thread by default, so plain
    integer increments are safe without locking.
    """

    submitted: int = 0
    completed: int = 0
    timed_out: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def reset(self) -> None:
        self.submitted = 0
        self.completed = 0
        self.timed_out = 0
        self.started_at = time.monotonic()

    @property
    def timeout_rate(self) -> float:
        finished = self.completed + self.timed_out
        return (self.timed_out / finished) if finished else 0.0

    @property
    def throughput_per_s(self) -> float:
        elapsed = max(time.monotonic() - self.started_at, 1e-9)
        return self.completed / elapsed


COUNTERS = HotPathCounters()


def record_submitted() -> None:
    COUNTERS.submitted += 1


def record_completion(environment, elapsed_ms: float) -> None:
    """Record an end-to-end verification completion (submit -> completed)."""
    COUNTERS.completed += 1
    # Fire a synthetic request event so Locust aggregates completion-time
    # percentiles for us and the metric shows up in the standard stats table.
    environment.events.request.fire(
        request_type=HOTPATH_TYPE,
        name=COMPLETION_METRIC,
        response_time=elapsed_ms,
        response_length=0,
        exception=None,
        context={},
    )


def record_timeout(environment) -> None:
    COUNTERS.timed_out += 1


# --- Threshold evaluation ---------------------------------------------------

@dataclass
class Breach:
    metric: str
    observed: float
    limit: float


def _completion_p95(environment) -> float | None:
    entry = environment.stats.get(COMPLETION_METRIC, HOTPATH_TYPE)
    if entry is None or entry.num_requests == 0:
        return None
    return entry.get_response_time_percentile(0.95)


def evaluate(environment, profile: Profile) -> tuple[list[Breach], list[str]]:
    """Return (breaches, summary_lines) for the completed run."""
    t = profile.thresholds
    total = environment.stats.total
    breaches: list[Breach] = []

    p95 = total.get_response_time_percentile(0.95)
    p99 = total.get_response_time_percentile(0.99)
    error_rate = total.fail_ratio
    completion_p95 = _completion_p95(environment)
    timeout_rate = COUNTERS.timeout_rate

    if t.max_p95_ms is not None and p95 > t.max_p95_ms:
        breaches.append(Breach("p95_ms", p95, t.max_p95_ms))
    if t.max_p99_ms is not None and p99 > t.max_p99_ms:
        breaches.append(Breach("p99_ms", p99, t.max_p99_ms))
    if t.max_error_rate is not None and error_rate > t.max_error_rate:
        breaches.append(Breach("error_rate", error_rate, t.max_error_rate))
    if t.max_timeout_rate is not None and timeout_rate > t.max_timeout_rate:
        breaches.append(Breach("timeout_rate", timeout_rate, t.max_timeout_rate))
    if (
        t.max_verification_completion_ms is not None
        and completion_p95 is not None
        and completion_p95 > t.max_verification_completion_ms
    ):
        breaches.append(
            Breach("completion_p95_ms", completion_p95, t.max_verification_completion_ms)
        )

    summary = [
        f"profile               : {profile.name}",
        f"requests              : {total.num_requests}  (failures: {total.num_failures})",
        f"throughput (req/s)    : {total.total_rps:.1f}",
        f"latency p50/p95/p99 ms: {total.get_response_time_percentile(0.5):.0f} / "
        f"{p95:.0f} / {p99:.0f}",
        f"error rate            : {error_rate:.4f}",
        f"verifications submitted: {COUNTERS.submitted}",
        f"verifications completed: {COUNTERS.completed}",
        f"poll timeout rate     : {timeout_rate:.4f}",
        f"worker throughput v/s : {COUNTERS.throughput_per_s:.2f}",
        "completion p95 ms     : "
        + (f"{completion_p95:.0f}" if completion_p95 is not None else "n/a (no worker)"),
    ]
    if not profile.expect_completion:
        summary.append(
            "note                  : completion/worker metrics not enforced "
            "(expect_completion=false)"
        )
    return breaches, summary
