import { redirect } from "next/navigation";

import { DegradedNote, NoProject } from "@/components/layout/page-helpers";
import { StatusBadge, VerdictBadge } from "@/components/ui/badges";
import { PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { StatCard, TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp } from "@/lib/api/server";
import type { Verification } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { pct, relativeTime, score, shortId } from "@/lib/format";
import { safe } from "@/lib/safe";

export const dynamic = "force-dynamic";
export const metadata = { title: "Runs" };

export default async function RunsPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;
  if (!pid) return (<><PageHeader title="Runs" description="Every artifact submitted for verification." /><NoProject /></>);

  const [runs, failed] = await safe(
    cp.get<Verification[]>("/v1/verifications", { project_id: pid, limit: 200 }),
    [],
  );

  const passed = runs.filter((r) => r.passed === true).length;
  const failedRuns = runs.filter((r) => r.passed === false).length;
  const avgLatency =
    runs.filter((r) => r.latency_ms !== null).reduce((s, r) => s + (r.latency_ms ?? 0), 0) /
    Math.max(1, runs.filter((r) => r.latency_ms !== null).length);

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every artifact submitted for verification, with its grade and risk."
      />
      {failed && <DegradedNote what="Runs" />}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total runs" value={runs.length} />
        <StatCard label="Passed" value={passed} sub={runs.length ? pct(passed / runs.length, 0) : "—"} />
        <StatCard label="Failed" value={failedRuns} />
        <StatCard label="Avg latency" value={runs.length ? `${Math.round(avgLatency)}ms` : "—"} />
      </div>

      {runs.length === 0 ? (
        <EmptyState
          title="No runs yet"
          description="Submit an artifact to one of your verifiers — through the SDK or API — to see graded runs here."
        />
      ) : (
        <Table>
          <THead>
            <TH>Run</TH><TH>Verifier</TH><TH>Status</TH><TH>Verdict</TH>
            <TH align="right">Score</TH><TH align="right">Uncertainty</TH>
            <TH align="right">Risk</TH><TH align="right">Latency</TH><TH align="right">When</TH>
          </THead>
          <TBody>
            {runs.map((r) => (
              <TR key={r.id}>
                <TD><Value className="text-[13px] text-muted">{shortId(r.id)}</Value></TD>
                <TD><Value className="text-[13px] text-muted">{shortId(r.verifier_id)}</Value></TD>
                <TD><StatusBadge status={r.status} /></TD>
                <TD><VerdictBadge passed={r.passed} /></TD>
                <TD align="right"><Value>{score(r.score)}</Value></TD>
                <TD align="right"><Value className="text-muted">{score(r.uncertainty, 2)}</Value></TD>
                <TD align="right"><Value>{r.risk_score === null ? "—" : pct(r.risk_score, 0)}</Value></TD>
                <TD align="right"><Value className="text-muted">{r.latency_ms === null ? "—" : `${r.latency_ms}ms`}</Value></TD>
                <TD align="right"><span className="text-2xs text-faint">{relativeTime(r.created_at)}</span></TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </>
  );
}
