import { redirect } from "next/navigation";

import { DegradedNote } from "@/components/layout/page-helpers";
import { Badge, Card, CardBody, CardHeader, PageHeader } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { StatCard } from "@/components/ui/table";
import { ivp } from "@/lib/api/server";
import { resolveContext } from "@/lib/context";
import { pct } from "@/lib/format";
import { safe } from "@/lib/safe";

export const dynamic = "force-dynamic";
export const metadata = { title: "Operations" };

interface OpsStatus {
  region_id: string;
  locality: string;
  slo: {
    objective: number;
    latency_threshold_s: number | null;
    samples: number;
    attainment: number;
    error_budget_remaining: number;
    burn_rate: number;
  };
  chaos_armed: string[];
  resilience: { bulkhead_inflight: number; bulkhead_limit: number; breaker_state: string };
  warm_pool?: {
    size: number; idle: number; warm_hits: number; cold_spills: number; exhausted: number;
  };
}

const BREAKER_TONE: Record<string, "pass" | "warn" | "crit"> = {
  closed: "pass",
  half_open: "warn",
  open: "crit",
};

export default async function OperationsPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  const [status, failed] = await safe(ivp.get<OpsStatus>("/v1/ops/status"), null);

  return (
    <>
      <PageHeader
        title="Inline plane operations"
        description="Live region, SLO attainment, resilience state, and warm-pool utilization for the Inline Verification Plane."
      />
      {failed && <DegradedNote what="Inline plane status" />}

      {!status ? (
        <EmptyState
          title="No inline plane reachable"
          description="The IVP did not respond. It runs as a separate service (default port 8050); set IVP_URL for the dashboard to reach it."
        />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <StatCard label="Region" accent value={status.region_id} sub={status.locality} />
            <StatCard
              label="SLO attainment"
              value={pct(status.slo.attainment, 3)}
              sub={`objective ${pct(status.slo.objective, 2)} · ${status.slo.samples} samples`}
            />
            <StatCard
              label="Error budget"
              value={pct(Math.max(0, status.slo.error_budget_remaining), 1)}
              sub={status.slo.error_budget_remaining < 0 ? "budget blown" : "remaining"}
            />
            <StatCard
              label="Burn rate"
              value={`${status.slo.burn_rate.toFixed(2)}×`}
              sub={status.slo.burn_rate > 1 ? "above budget" : "within budget"}
            />
          </div>

          <Card>
            <CardHeader>
              <span className="text-sm font-medium text-ink">Resilience</span>
            </CardHeader>
            <CardBody className="flex flex-wrap items-center gap-x-8 gap-y-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">Circuit breaker</span>
                <Badge tone={BREAKER_TONE[status.resilience.breaker_state] ?? "muted"} dot>
                  {status.resilience.breaker_state}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">Bulkhead</span>
                <span className="data text-sm text-ink">
                  {status.resilience.bulkhead_inflight} / {status.resilience.bulkhead_limit} in flight
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">Chaos faults armed</span>
                {status.chaos_armed.length === 0 ? (
                  <Badge tone="muted">none</Badge>
                ) : (
                  status.chaos_armed.map((f) => <Badge key={f} tone="warn">{f}</Badge>)
                )}
              </div>
            </CardBody>
          </Card>

          {status.warm_pool && (
            <Card>
              <CardHeader>
                <span className="text-sm font-medium text-ink">Warm sandbox pool</span>
              </CardHeader>
              <CardBody className="grid grid-cols-2 gap-4 md:grid-cols-5">
                <StatCard label="Pool size" value={status.warm_pool.size} />
                <StatCard label="Idle (warm)" value={status.warm_pool.idle} />
                <StatCard label="Warm hits" value={status.warm_pool.warm_hits} />
                <StatCard label="Cold spills" value={status.warm_pool.cold_spills} />
                <StatCard label="Exhausted" value={status.warm_pool.exhausted} />
              </CardBody>
            </Card>
          )}

          <p className="text-2xs text-faint">
            These are live mechanism metrics. SLO figures reflect decisions served by this
            replica; they are not a production reliability guarantee.
          </p>
        </div>
      )}
    </>
  );
}
