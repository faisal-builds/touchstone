import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { Sparkline } from "@/components/charts/charts";
import { RobustnessGauge } from "@/components/charts/gauge";
import { NoProject } from "@/components/layout/page-helpers";
import { SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Badge, Card, CardBody, CardHeader, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp, rhd } from "@/lib/api/server";
import type { Evaluation, Exploit, Trend, Verification, Verifier } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { categoryLabel, pct, relativeTime, score, shortId, titleCase } from "@/lib/format";
import { safe } from "@/lib/safe";
import { LaunchEvaluation } from "./launch-evaluation";

export const dynamic = "force-dynamic";

export default async function VerifierDetailPage({ params }: { params: { id: string } }) {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;
  if (!pid) return (<><PageHeader title="Verifier" /><NoProject /></>);

  const [verifiers] = await safe(cp.get<Verifier[]>(`/v1/projects/${pid}/verifiers`), []);
  const verifier = verifiers.find((v) => v.id === params.id);
  if (!verifier) notFound();

  const [[evaluations], [exploits], [trend], [runs]] = await Promise.all([
    safe(rhd.get<Evaluation[]>(`/v1/robustness/verifiers/${params.id}/evaluations`), []),
    safe(rhd.get<Exploit[]>(`/v1/robustness/verifiers/${params.id}/exploits`), []),
    safe(rhd.get<Trend>(`/v1/robustness/verifiers/${params.id}/trend`), { verifier_id: params.id, direction: "insufficient_data", history: [] } as Trend),
    safe(cp.get<Verification[]>("/v1/verifications", { verifier_id: params.id, limit: 6 }), []),
  ]);

  const latest = evaluations.find((e) => e.status === "completed");
  const gaugeValue = latest?.robustness_score ?? verifier.robustness_score ?? null;

  return (
    <>
      <div className="mb-1">
        <Link href="/verifiers" className="text-2xs font-medium text-muted hover:text-ink">← Verifiers</Link>
      </div>
      <PageHeader
        title={verifier.name}
        description={`${titleCase(verifier.verifier_type)} verifier · version ${verifier.version} · ${verifier.slug}`}
        actions={<LaunchEvaluation verifierId={params.id} />}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Gauge hero */}
        <Card className="lg:col-span-1">
          <CardHeader><Eyebrow>Verifier robustness</Eyebrow></CardHeader>
          <CardBody className="flex flex-col items-center">
            <RobustnessGauge value={gaugeValue} ci={latest?.ci ?? null} size={240} />
            <div className="mt-4 flex items-center gap-4 text-xs text-muted">
              {latest?.ci && (
                <span className="data">
                  95% CI {pct(latest.ci.low, 0)}–{pct(latest.ci.high, 0)}
                </span>
              )}
              {trend.history.length >= 2 && (
                <span className="flex items-center gap-1.5">
                  <Sparkline data={trend.history} width={64} height={20} />
                  {titleCase(trend.direction)}
                </span>
              )}
            </div>
          </CardBody>
        </Card>

        {/* Key facts */}
        <Card className="lg:col-span-2">
          <CardHeader><Eyebrow>Latest evaluation</Eyebrow></CardHeader>
          <CardBody>
            {latest ? (
              <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
                <Fact label="Robustness" value={pct(latest.robustness_score)} />
                <Fact label="Weighted" value={pct(latest.weighted_robustness_score)} />
                <Fact label="Attacks" value={`${latest.executed}/${latest.total_attacks}`} />
                <Fact label="Exploits" value={String(latest.exploits_found)} />
                <Fact label="Seed" value={String(latest.seed)} />
                <Fact label="Errored" value={String(latest.errored)} />
                <Fact label="Version" value={`v${latest.verifier_version}`} />
                <Fact label="Status" value={titleCase(latest.status)} />
              </div>
            ) : (
              <EmptyState
                title="Not evaluated yet"
                description="Launch a robustness evaluation to attack this verifier and measure how well it resists manipulation."
              />
            )}
          </CardBody>
        </Card>
      </div>

      {/* Evaluations + exploits */}
      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex items-center justify-between">
            <Eyebrow>Evaluations</Eyebrow>
            <Link href="/robustness" className="text-2xs font-medium text-muted hover:text-ink">All →</Link>
          </CardHeader>
          <CardBody className="p-0">
            {evaluations.length === 0 ? (
              <p className="p-5 text-sm text-muted">No evaluations yet.</p>
            ) : (
              <Table>
                <THead>
                  <TH>Evaluation</TH><TH>Status</TH><TH align="right">Robustness</TH><TH align="right">Exploits</TH>
                </THead>
                <TBody>
                  {evaluations.slice(0, 6).map((e) => (
                    <TR key={e.id}>
                      <TD>
                        <Link href={`/robustness/${e.id}`} className="data text-[13px] text-muted hover:text-ink">
                          {shortId(e.id)}
                        </Link>
                        <div className="text-2xs text-faint">v{e.verifier_version}</div>
                      </TD>
                      <TD><StatusBadge status={e.status} /></TD>
                      <TD align="right"><Value>{pct(e.robustness_score, 0)}</Value></TD>
                      <TD align="right"><Value>{e.exploits_found}</Value></TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader className="flex items-center justify-between">
            <Eyebrow>Discovered exploits</Eyebrow>
            <Link href={`/exploits?verifier_id=${params.id}`} className="text-2xs font-medium text-muted hover:text-ink">
              Search →
            </Link>
          </CardHeader>
          <CardBody className="p-0">
            {exploits.length === 0 ? (
              <p className="p-5 text-sm text-muted">No exploits found. This verifier resisted every attack so far.</p>
            ) : (
              <ul className="divide-y divide-line">
                {exploits.slice(0, 6).map((ex) => (
                  <li key={ex.signature} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <Badge tone="info">{categoryLabel(ex.category)}</Badge>
                      <SeverityBadge severity={ex.severity} />
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-[13px] text-muted">{ex.failure_reason || ex.description}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Recent runs */}
      <Card className="mt-6">
        <CardHeader><Eyebrow>Recent runs</Eyebrow></CardHeader>
        <CardBody className="p-0">
          {runs.length === 0 ? (
            <p className="p-5 text-sm text-muted">No runs for this verifier yet.</p>
          ) : (
            <Table>
              <THead>
                <TH>Run</TH><TH>Status</TH><TH align="right">Score</TH>
                <TH align="right">Risk</TH><TH align="right">When</TH>
              </THead>
              <TBody>
                {runs.map((r) => (
                  <TR key={r.id}>
                    <TD><Value className="text-[13px] text-muted">{shortId(r.id)}</Value></TD>
                    <TD><StatusBadge status={r.status} /></TD>
                    <TD align="right"><Value>{score(r.score)}</Value></TD>
                    <TD align="right"><Value>{r.risk_score === null ? "—" : pct(r.risk_score, 0)}</Value></TD>
                    <TD align="right"><span className="text-2xs text-faint">{relativeTime(r.created_at)}</span></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-2xs font-medium uppercase tracking-wider text-faint">{label}</p>
      <p className="mt-0.5 data text-sm font-semibold text-ink">{value}</p>
    </div>
  );
}
