import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { CategoryBreakdown } from "@/components/charts/charts";
import { RobustnessGauge } from "@/components/charts/gauge";
import { SeverityBadge, StatusBadge } from "@/components/ui/badges";
import { Badge, Card, CardBody, CardHeader, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/states";
import { rhd } from "@/lib/api/server";
import type { EvaluationReport } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { categoryLabel, pct, titleCase } from "@/lib/format";
import { safe } from "@/lib/safe";
import { DownloadReport } from "./download-report";

export const dynamic = "force-dynamic";

export default async function ReportPage({ params }: { params: { evalId: string } }) {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  const [report, failed] = await safe(
    rhd.get<EvaluationReport>(`/v1/robustness/evaluations/${params.evalId}/report`),
    null as unknown as EvaluationReport,
  );
  if (failed || !report) {
    if (!report) notFound();
    return <ErrorState detail="This evaluation report couldn't be loaded." />;
  }
  const e = report.evaluation;

  return (
    <>
      <div className="mb-1">
        <Link href="/robustness" className="text-2xs font-medium text-muted hover:text-ink">← Robustness</Link>
      </div>
      <PageHeader
        title="Evaluation report"
        description={`Reproducible from seed ${report.seed} · verifier version ${e.verifier_version}`}
        actions={<DownloadReport evalId={params.evalId} />}
      />

      {e.status === "failed" ? (
        <ErrorState title="This evaluation failed" detail={e.error ?? undefined} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <Card>
              <CardHeader><Eyebrow>Robustness</Eyebrow></CardHeader>
              <CardBody className="flex flex-col items-center">
                <RobustnessGauge value={e.robustness_score} ci={e.ci} size={230} />
                {e.ci && (
                  <p className="data mt-3 text-xs text-muted">
                    95% CI {pct(e.ci.low, 1)} – {pct(e.ci.high, 1)}
                  </p>
                )}
              </CardBody>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="flex items-center justify-between">
                <Eyebrow>Summary</Eyebrow>
                <StatusBadge status={e.status} />
              </CardHeader>
              <CardBody>
                <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
                  <Fact label="Robustness" value={pct(e.robustness_score)} />
                  <Fact label="Weighted" value={pct(e.weighted_robustness_score)} />
                  <Fact label="Total attacks" value={String(e.total_attacks)} />
                  <Fact label="Executed" value={String(e.executed)} />
                  <Fact label="Errored" value={String(e.errored)} />
                  <Fact label="Exploits" value={String(e.exploits_found)} />
                  <Fact label="Seed" value={String(report.seed)} />
                  <Fact label="Max attacks" value={String(report.config?.max_attacks ?? "—")} />
                </div>
                <div className="mt-5 border-t border-line pt-4">
                  <Eyebrow>Exploits by category</Eyebrow>
                  <div className="mt-2">
                    <CategoryBreakdown counts={report.category_counts} />
                  </div>
                </div>
              </CardBody>
            </Card>
          </div>

          <Card className="mt-6">
            <CardHeader><Eyebrow>Discovered exploits · {report.exploits.length}</Eyebrow></CardHeader>
            <CardBody className="p-0">
              {report.exploits.length === 0 ? (
                <p className="p-5 text-sm text-muted">
                  No exploits. The verifier resisted every adversarial attempt in this evaluation.
                </p>
              ) : (
                <ul className="divide-y divide-line">
                  {report.exploits.map((ex) => (
                    <li key={ex.signature} className="px-5 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="info">{categoryLabel(ex.category)}</Badge>
                        <SeverityBadge severity={ex.severity} />
                        <Value className="text-2xs text-faint">{ex.strategy}</Value>
                        {ex.occurrences > 1 && (
                          <span className="text-2xs text-faint">seen {ex.occurrences}×</span>
                        )}
                        <span className="ml-auto data text-xs text-muted">
                          verifier scored {ex.verifier_score.toFixed(2)}
                        </span>
                      </div>
                      <p className="mt-2 text-[13px] text-ink">{ex.failure_reason || ex.description}</p>
                      <pre className="mt-2 max-h-32 overflow-auto rounded-md border border-line bg-paper p-3 text-2xs text-muted">
                        {JSON.stringify(ex.artifact, null, 2)}
                      </pre>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </>
      )}
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
