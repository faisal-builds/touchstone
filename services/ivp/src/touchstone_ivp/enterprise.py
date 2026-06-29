"""Enterprise context for the inline plane.

Bundles the multi-region/operability concerns the plane consults on the hot path,
all optional so the core plane runs unchanged without them:

* **region** — the local region id/locality this replica serves, stamped onto
  every decision and exposed for region-aware routing/failover upstream;
* **SLO** — records each decision's latency against the inline latency objective,
  so attainment / error-budget / burn-rate are live;
* **chaos** — a :class:`FaultInjector` consulted at named failpoints, so game-days
  (and tests) can drive the plane through injected latency/errors and confirm it
  degrades correctly.

These are mechanisms. The SLO numbers and chaos findings only become meaningful
against real traffic; here they are wired and correct, not production-proven.
"""

from __future__ import annotations

from touchstone_fleet import SLO, FaultInjector, SLOTracker


class EnterpriseContext:
    def __init__(
        self, *, region_id: str = "local", locality: str = "local",
        latency_slo_objective: float = 0.999, latency_threshold_s: float = 0.15,
        slo_window: int = 50_000, injector: FaultInjector | None = None,
    ) -> None:
        self.region_id = region_id
        self.locality = locality
        self.slo = SLOTracker(
            SLO("inline-latency", objective=latency_slo_objective,
                latency_threshold_s=latency_threshold_s),
            window=slo_window,
        )
        self.injector = injector or FaultInjector()

    # Hot-path hooks (cheap no-ops unless a fault is armed) -------------------
    def failpoint(self, name: str) -> None:
        self.injector.failpoint(name)

    def injected_latency(self, name: str) -> float:
        return self.injector.latency(name)

    def record_latency(self, latency_ms: float) -> None:
        self.slo.record(latency_s=latency_ms / 1000.0)

    def status(self) -> dict:
        return {
            "region_id": self.region_id,
            "locality": self.locality,
            "slo": {
                "objective": self.slo.slo.objective,
                "latency_threshold_s": self.slo.slo.latency_threshold_s,
                "samples": self.slo.total,
                "attainment": round(self.slo.attainment(), 6),
                "error_budget_remaining": round(self.slo.error_budget_remaining(), 6),
                "burn_rate": round(self.slo.burn_rate(), 4),
            },
            "chaos_armed": [name for name in ("ivp.verify", "ivp.fast")
                            if self.injector.armed(name)],
        }
