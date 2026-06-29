import Link from "next/link";
import { redirect } from "next/navigation";

import { SeverityStrip } from "@/components/charts/charts";
import { DegradedNote, NoProject } from "@/components/layout/page-helpers";
import { StatusBadge, VerdictBadge } from "@/components/ui/badges";
import { Card, CardBody, CardHeader, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { StatCard, TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp, rhd } from "@/lib/api/server";
import type { Exploit, Verification, Verifier } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { BAND_COLOR, pct, relativeTime, robustnessBand, score, shortId } from "@/lib/format";
import { safe } from "@/lib/safe";

export const dynamic = "force-dynamic";
export const metadata = { title: "Overview" };

export default async function DashboardPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;

  if (!pid) {
    return (
      <>
        <PageHeader title="Overview" description="A live read on your verification layer." />
        <NoProject />
      </>
    );
  }

  const [[verifiers, e1], [runs, e2], [exploits, e3]] = await Promise.all([
    safe(cp.get<Verifier[]>(`/v1/projects/${pid}/verifiers`), []),
    safe(cp.get<Verification[]>("/v1/verifications", { project_id: pid, limit: 8 }), []),
    safe(rhd.get<Exploit[]>("/v1/robustness/exploits/search", { limit: 500 }), []),
  ]);
  const degraded = e1 || e2 || e3;

  const scored = verifiers.filter((v) => v.robustness_score !== null);
  const avgRobustness =
    scored.length > 0
      ? scored.reduce((s, v) => s + (v.robustness_score ?? 0), 0) / scored.length
      : null;
  const sevCounts = exploits.reduce<Record<string, number>>((acc, ex) => {
    acc[ex.severity] = (acc[ex.severity] ?? 0) + 1;
    return acc;
  }, {});
  const leaderboard = [...scored].sort(
    (a, b) => (a.robustness_score ?? 0) - (b.robustness_score ?? 0),
  ).slice(0, 5);

  return (
    <>
      <PageHeader
        title="Overview"
        description="A live read on your verifiers, runs, risk, and robustness."
      />
      {degraded && <DegradedNote />}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Verifiers" value={verifiers.length}
          sub={`${verifiers.filter((v) => v.is_active).length} active`} />
        <StatCard label="Mean robustness" accent
          value={avgRobustness === null ? "—" : pct(avgRobustness)}
          sub={scored.length ? `across ${scored.length} evaluated` : "none evaluated yet"} />
        <StatCard label="Recent runs" value={runs.length}
          sub={`${runs.filter((r) => r.passed).length} passed`} />
        <StatCard label="Exploits in corpus" value={exploits.length}>
          <SeverityStrip counts={sevCounts} />
        </StatCard>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Recent runs */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex items-center justify-between">
            <Eyebrow>Recent runs</Eyebrow>
            <Link href="/verifications" className="text-2xs font-medium text-muted hover:text-ink">
              View all →
            </Link>
          </CardHeader>
          <div className="p-0">
            {runs.length === 0 ? (
              <div className="p-5">
                <EmptyState title="No runs yet"
                  description="Submit an artifact to a verifier to see graded runs here." />
              </div>
            ) : (
              <Table>
                <THead>
                  <TH>Run</TH><TH>Status</TH><TH>Verdict</TH>
                  <TH align="right">Score</TH><TH align="right">Risk</TH><TH align="right">When</TH>
                </THead>
                <TBody>
                  {runs.map((r) => (
                    <TR key={r.id}>
                      <TD><Value className="text-[13px] text-muted">{shortId(r.id)}</Value></TD>
                      <TD><StatusBadge status={r.status} /></TD>
                      <TD><VerdictBadge passed={r.passed} /></TD>
                      <TD align="right"><Value>{score(r.score, 3)}</Value></TD>
                      <TD align="right"><Value>{r.risk_score === null ? "—" : pct(r.risk_score, 0)}</Value></TD>
                      <TD align="right"><span className="text-2xs text-faint">{relativeTime(r.created_at)}</span></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </div>
        </Card>

        {/* Robustness leaderboard (weakest first — the ones to fix) */}
        <Card>
          <CardHeader className="flex items-center justify-between">
            <Eyebrow>Needs attention</Eyebrow>
            <Link href="/robustness" className="text-2xs font-medium text-muted hover:text-ink">
              Robustness →
            </Link>
          </CardHeader>
          <CardBody className="p-0">
            {leaderboard.length === 0 ? (
              <div className="p-5">
                <p className="text-sm text-muted">
                  No verifier has been evaluated yet. Launch a robustness evaluation to populate this.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {leaderboard.map((v) => {
                  const band = robustnessBand(v.robustness_score);
                  return (
                    <li key={v.id}>
                      <Link href={`/verifiers/${v.id}`}
                        className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-paper">
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] font-medium text-ink">{v.name}</span>
                          <span className="block text-2xs text-faint">v{v.version} · {v.verifier_type}</span>
                        </span>
                        <Value className={`text-sm font-semibold ${BAND_COLOR[band]}`}>
                          {pct(v.robustness_score, 0)}
                        </Value>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
