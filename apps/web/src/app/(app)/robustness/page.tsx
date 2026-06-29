import Link from "next/link";
import { redirect } from "next/navigation";

import { DegradedNote, NoProject } from "@/components/layout/page-helpers";
import { StatusBadge } from "@/components/ui/badges";
import { PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { StatCard, TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp, rhd } from "@/lib/api/server";
import type { Evaluation, Verifier } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { BAND_COLOR, pct, robustnessBand, shortId } from "@/lib/format";
import { safe } from "@/lib/safe";
import { CompareEvaluations } from "./compare";

export const dynamic = "force-dynamic";
export const metadata = { title: "Robustness" };

export default async function RobustnessPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;
  if (!pid) return (<><PageHeader title="Robustness" description="How well your verifiers resist manipulation." /><NoProject /></>);

  const [verifiers, vFailed] = await safe(cp.get<Verifier[]>(`/v1/projects/${pid}/verifiers`), []);
  const nameById = new Map(verifiers.map((v) => [v.id, v.name]));

  const evalLists = await Promise.all(
    verifiers.map((v) =>
      safe(rhd.get<Evaluation[]>(`/v1/robustness/verifiers/${v.id}/evaluations`), []),
    ),
  );
  const evaluations = evalLists.flatMap(([list]) => list);
  const degraded = vFailed || evalLists.some(([, f]) => f);

  const completed = evaluations.filter((e) => e.status === "completed");
  const avg = completed.length
    ? completed.reduce((s, e) => s + (e.robustness_score ?? 0), 0) / completed.length
    : null;
  const totalExploits = completed.reduce((s, e) => s + e.exploits_found, 0);

  return (
    <>
      <PageHeader
        title="Robustness"
        description="Each evaluation attacks a verifier with adversarial artifacts and scores how often it was fooled."
      />
      {degraded && <DegradedNote what="Some evaluations" />}

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Evaluations" value={evaluations.length} sub={`${completed.length} completed`} />
        <StatCard label="Mean robustness" accent value={avg === null ? "—" : pct(avg)} />
        <StatCard label="Exploits found" value={totalExploits} />
        <StatCard label="Verifiers covered"
          value={new Set(completed.map((e) => e.verifier_id)).size}
          sub={`of ${verifiers.length}`} />
      </div>

      <div className="mb-6">
        <CompareEvaluations evaluations={evaluations} />
      </div>

      {evaluations.length === 0 ? (
        <EmptyState
          title="No evaluations yet"
          description="Open a verifier and launch a robustness evaluation to populate this page."
        />
      ) : (
        <Table>
          <THead>
            <TH>Evaluation</TH><TH>Verifier</TH><TH align="right">Ver.</TH>
            <TH>Status</TH><TH align="right">Robustness</TH><TH align="right">Weighted</TH>
            <TH align="right">Exploits</TH><TH align="right">Attacks</TH><TH></TH>
          </THead>
          <TBody>
            {evaluations.map((e) => {
              const band = robustnessBand(e.robustness_score);
              return (
                <TR key={e.id}>
                  <TD>
                    <Link href={`/robustness/${e.id}`} className="data text-[13px] text-muted hover:text-ink">
                      {shortId(e.id)}
                    </Link>
                  </TD>
                  <TD>
                    <Link href={`/verifiers/${e.verifier_id}`} className="text-[13px] font-medium text-ink hover:underline">
                      {nameById.get(e.verifier_id) ?? shortId(e.verifier_id)}
                    </Link>
                  </TD>
                  <TD align="right"><Value className="text-muted">v{e.verifier_version}</Value></TD>
                  <TD><StatusBadge status={e.status} /></TD>
                  <TD align="right"><Value className={`font-semibold ${BAND_COLOR[band]}`}>{pct(e.robustness_score, 0)}</Value></TD>
                  <TD align="right"><Value className="text-muted">{pct(e.weighted_robustness_score, 0)}</Value></TD>
                  <TD align="right"><Value>{e.exploits_found}</Value></TD>
                  <TD align="right"><Value className="text-muted">{e.executed}/{e.total_attacks}</Value></TD>
                  <TD align="right"><Link href={`/robustness/${e.id}`} className="text-2xs font-medium text-muted hover:text-ink">Report →</Link></TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </>
  );
}
