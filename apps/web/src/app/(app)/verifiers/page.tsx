import Link from "next/link";
import { redirect } from "next/navigation";

import { DegradedNote, NoProject } from "@/components/layout/page-helpers";
import { Badge, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp } from "@/lib/api/server";
import type { Verifier } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { BAND_COLOR, BAND_LABEL, pct, robustnessBand, titleCase } from "@/lib/format";
import { safe } from "@/lib/safe";
import { RegisterVerifier } from "./register-verifier";

export const dynamic = "force-dynamic";
export const metadata = { title: "Verifiers" };

export default async function VerifiersPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");
  const pid = ctx.activeProjectId;

  if (!pid) {
    return (
      <>
        <PageHeader title="Verifiers" description="The graders that decide whether an artifact passes." />
        <NoProject />
      </>
    );
  }

  const [verifiers, failed] = await safe(
    cp.get<Verifier[]>(`/v1/projects/${pid}/verifiers`),
    [],
  );

  return (
    <>
      <PageHeader
        title="Verifiers"
        description="The graders that decide whether an artifact passes — and how robust each one is."
        actions={<RegisterVerifier projectId={pid} />}
      />
      {failed ? (
        <ErrorState detail="The verifier registry didn't respond. Check the control-plane is reachable." />
      ) : verifiers.length === 0 ? (
        <EmptyState
          title="No verifiers yet"
          description="Register your first verifier to start grading artifacts and measuring robustness."
        />
      ) : (
        <Table>
          <THead>
            <TH>Name</TH><TH>Type</TH><TH align="right">Version</TH>
            <TH>Status</TH><TH align="right">Robustness</TH><TH></TH>
          </THead>
          <TBody>
            {verifiers.map((v) => {
              const band = robustnessBand(v.robustness_score);
              return (
                <TR key={v.id}>
                  <TD>
                    <Link href={`/verifiers/${v.id}`} className="font-medium text-ink hover:underline">
                      {v.name}
                    </Link>
                    <div className="text-2xs text-faint data">{v.slug}</div>
                  </TD>
                  <TD><Badge tone="info">{titleCase(v.verifier_type)}</Badge></TD>
                  <TD align="right"><Value className="text-muted">v{v.version}</Value></TD>
                  <TD>
                    {v.is_active
                      ? <Badge tone="pass" dot>Active</Badge>
                      : <Badge tone="muted" dot>Inactive</Badge>}
                  </TD>
                  <TD align="right">
                    <Value className={`font-semibold ${BAND_COLOR[band]}`}>
                      {pct(v.robustness_score, 0)}
                    </Value>
                    <div className="text-2xs text-faint">{BAND_LABEL[band]}</div>
                  </TD>
                  <TD align="right">
                    <Link href={`/verifiers/${v.id}`} className="text-2xs font-medium text-muted hover:text-ink">
                      Details →
                    </Link>
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </>
  );
}
