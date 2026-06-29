import { redirect } from "next/navigation";

import { BarRow } from "@/components/charts/charts";
import { DegradedNote, NoProject } from "@/components/layout/page-helpers";
import { Badge, Card, CardBody, CardHeader, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { StatCard, TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp } from "@/lib/api/server";
import type { Verification } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { pct, relativeTime, riskBand, score, shortId } from "@/lib/format";
import { safe } from "@/lib/safe";

export const dynamic = "force-dynamic";
export const metadata = { title: "Risk" };

const BANDS = [
  { key: "low", label: "Low (< 30%)", min: 0, max: 0.3, tone: "#2F7D5B" },
  { key: "medium", label: "Medium (30–60%)", min: 0.3, max: 0.6, tone: "#B5832B" },
  { key: "high", label: "High (≥ 60%)", min: 0.6, max: 1.01, tone: "#C2533B" },
];

export default async function RiskPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;
  if (!pid) return (<><PageHeader title="Risk" description="How risky each verification looks." /><NoProject /></>);

  const [runs, failed] = await safe(
    cp.get<Verification[]>("/v1/verifications", { project_id: pid, limit: 200 }),
    [],
  );
  const scored = runs.filter((r) => r.risk_score !== null) as (Verification & { risk_score: number })[];

  const dist = BANDS.map((b) => ({
    ...b,
    count: scored.filter((r) => r.risk_score >= b.min && r.risk_score < b.max).length,
  }));
  const maxCount = Math.max(1, ...dist.map((d) => d.count));
  const avgRisk = scored.length ? scored.reduce((s, r) => s + r.risk_score, 0) / scored.length : null;
  const topRisk = [...scored].sort((a, b) => b.risk_score - a.risk_score).slice(0, 10);

  return (
    <>
      <PageHeader
        title="Risk"
        description="The risk engine scores every completed verification from its grade and uncertainty."
      />
      {failed && <DegradedNote what="Risk scores" />}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Scored runs" value={scored.length} />
        <StatCard label="Mean risk" accent value={avgRisk === null ? "—" : pct(avgRisk, 0)} />
        <StatCard label="High risk" value={dist[2]?.count ?? 0} sub="≥ 60%" />
        <StatCard label="Low risk" value={dist[0]?.count ?? 0} sub="< 30%" />
      </div>

      {scored.length === 0 ? (
        <EmptyState
          title="No risk scores yet"
          description="Once verifications complete, the risk engine scores each one and they appear here."
        />
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <Card>
            <CardHeader><Eyebrow>Risk distribution</Eyebrow></CardHeader>
            <CardBody>
              {dist.map((b) => (
                <BarRow key={b.key} label={b.label} value={b.count} max={maxCount} tone={b.tone} />
              ))}
            </CardBody>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader><Eyebrow>Highest-risk runs</Eyebrow></CardHeader>
            <CardBody className="p-0">
              <Table>
                <THead>
                  <TH>Run</TH><TH>Verifier</TH><TH>Band</TH>
                  <TH align="right">Score</TH><TH align="right">Risk</TH><TH align="right">When</TH>
                </THead>
                <TBody>
                  {topRisk.map((r) => {
                    const band = riskBand(r.risk_score);
                    const tone = band === "weak" ? "risk" : band === "fair" ? "warn" : "pass";
                    return (
                      <TR key={r.id}>
                        <TD><Value className="text-[13px] text-muted">{shortId(r.id)}</Value></TD>
                        <TD><Value className="text-[13px] text-muted">{shortId(r.verifier_id)}</Value></TD>
                        <TD><Badge tone={tone}>{band === "weak" ? "High" : band === "fair" ? "Medium" : "Low"}</Badge></TD>
                        <TD align="right"><Value>{score(r.score)}</Value></TD>
                        <TD align="right"><Value className="font-semibold">{pct(r.risk_score, 0)}</Value></TD>
                        <TD align="right"><span className="text-2xs text-faint">{relativeTime(r.created_at)}</span></TD>
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
            </CardBody>
          </Card>
        </div>
      )}
    </>
  );
}
