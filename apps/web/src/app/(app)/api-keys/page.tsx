import { redirect } from "next/navigation";

import { Badge, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { cp } from "@/lib/api/server";
import type { ApiKey } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { relativeTime, titleCase } from "@/lib/format";
import { safe } from "@/lib/safe";
import { CreateApiKey } from "./create-key";

export const dynamic = "force-dynamic";
export const metadata = { title: "API keys" };

function keyStatus(k: ApiKey): { tone: "pass" | "muted" | "risk"; label: string } {
  if (k.revoked_at) return { tone: "risk", label: "Revoked" };
  if (k.expires_at && new Date(k.expires_at) < new Date()) return { tone: "muted", label: "Expired" };
  return { tone: "pass", label: "Active" };
}

export default async function ApiKeysPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  const [keys, failed] = await safe(cp.get<ApiKey[]>("/v1/api-keys"), []);

  return (
    <>
      <PageHeader
        title="API keys"
        description="Credentials for the SDK, CI, and the reward-hacking detector. Treat them like passwords."
        actions={<CreateApiKey projects={ctx.projects.map((p) => ({ id: p.id, name: p.name }))} />}
      />

      {failed ? (
        <ErrorState detail="Your keys didn't load. Check the control-plane is reachable." />
      ) : keys.length === 0 ? (
        <EmptyState
          title="No API keys yet"
          description="Create a key to call Touchstone from the SDK, your CI pipeline, or scripts."
        />
      ) : (
        <Table>
          <THead>
            <TH>Name</TH><TH>Key ID</TH><TH>Role</TH><TH>Scope</TH>
            <TH>Status</TH><TH align="right">Last used</TH>
          </THead>
          <TBody>
            {keys.map((k) => {
              const s = keyStatus(k);
              return (
                <TR key={k.id}>
                  <TD><span className="font-medium text-ink">{k.name}</span></TD>
                  <TD><Value className="text-[13px] text-muted">{k.key_id}</Value></TD>
                  <TD><Badge tone="info">{titleCase(k.role)}</Badge></TD>
                  <TD>
                    {k.project_id
                      ? <Value className="text-2xs text-faint">project-scoped</Value>
                      : <span className="text-2xs text-faint">organization</span>}
                  </TD>
                  <TD><Badge tone={s.tone} dot>{s.label}</Badge></TD>
                  <TD align="right">
                    <span className="text-2xs text-faint">
                      {k.last_used_at ? relativeTime(k.last_used_at) : "never"}
                    </span>
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
