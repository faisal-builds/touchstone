import { redirect } from "next/navigation";

import { Badge, Card, CardBody, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { CopyButton } from "@/components/ui/copy";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp } from "@/lib/api/server";
import type { AuditRecord } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { relativeTime, shortHash, titleCase } from "@/lib/format";
import { safe } from "@/lib/safe";

export const dynamic = "force-dynamic";
export const metadata = { title: "Audit trail" };

function eventTone(eventType: string): "pass" | "info" | "warn" | "risk" | "muted" {
  if (eventType.includes("login") || eventType.includes("signup")) return "info";
  if (eventType.includes("reward") || eventType.includes("risk")) return "warn";
  if (eventType.includes("failed")) return "risk";
  if (eventType.includes("completed") || eventType.includes("registered")) return "pass";
  return "muted";
}

export default async function AuditPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  const [records, failed] = await safe(
    cp.get<AuditRecord[]>("/v1/audit", { limit: 200 }),
    [],
  );

  return (
    <>
      <PageHeader
        title="Audit trail"
        description="A tamper-evident, hash-chained record of every action in your organization. Each entry commits to the one before it."
      />

      {failed ? (
        <ErrorState detail="The audit log didn't respond. Check the control-plane is reachable." />
      ) : records.length === 0 ? (
        <EmptyState
          title="No audit records yet"
          description="As users sign in, keys are created, and verifications run, each event is recorded into the chain and shown here."
        />
      ) : (
        <Card>
          <div className="flex items-center justify-between px-5 py-3">
            <Eyebrow>Chain · newest first</Eyebrow>
            <Badge tone="pass" dot>Integrity verified by recomputation</Badge>
          </div>
          <CardBody className="p-0">
            <Table>
              <THead>
                <TH align="right">#</TH><TH>Event</TH><TH>Actor</TH><TH>Resource</TH>
                <TH>Record hash</TH><TH>Prev</TH><TH align="right">When</TH>
              </THead>
              <TBody>
                {records.map((r) => (
                  <TR key={r.id}>
                    <TD align="right"><Value className="text-muted">{r.chain_index}</Value></TD>
                    <TD><Badge tone={eventTone(r.event_type)}>{titleCase(r.event_type)}</Badge></TD>
                    <TD>
                      <span className="text-[13px] text-ink">{titleCase(r.actor_type)}</span>
                      {r.actor_id && <div className="data text-2xs text-faint">{shortHash(r.actor_id, 10)}</div>}
                    </TD>
                    <TD>
                      {r.resource_type ? (
                        <span className="text-[13px] text-muted">{titleCase(r.resource_type)}</span>
                      ) : <span className="text-faint">—</span>}
                    </TD>
                    <TD>
                      <span className="inline-flex items-center gap-1.5">
                        <Value className="text-2xs text-ink">{shortHash(r.record_hash, 12)}</Value>
                        <CopyButton value={r.record_hash} label="" />
                      </span>
                    </TD>
                    <TD><Value className="text-2xs text-faint">{shortHash(r.prev_hash, 10)}</Value></TD>
                    <TD align="right"><span className="text-2xs text-faint">{relativeTime(r.occurred_at)}</span></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardBody>
        </Card>
      )}
    </>
  );
}
