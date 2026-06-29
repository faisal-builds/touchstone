import { redirect } from "next/navigation";

import { DegradedNote } from "@/components/layout/page-helpers";
import { Card, CardBody, CardHeader, Eyebrow, PageHeader, Value } from "@/components/ui/primitives";
import { EmptyState } from "@/components/ui/states";
import { cp } from "@/lib/api/server";
import type { Project, Workspace } from "@/lib/api/types";
import { resolveContext } from "@/lib/context";
import { safe } from "@/lib/safe";
import { CreateProject, CreateWorkspace } from "./manage";

export const dynamic = "force-dynamic";
export const metadata = { title: "Settings" };

export default async function SettingsPage() {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  const [workspaces, wFailed] = await safe(cp.get<Workspace[]>("/v1/workspaces"), []);
  const projectLists = await Promise.all(
    workspaces.map((w) => safe(cp.get<Project[]>(`/v1/workspaces/${w.id}/projects`), [])),
  );
  const projectsByWs = new Map(workspaces.map((w, i) => [w.id, projectLists[i]?.[0] ?? []]));

  return (
    <>
      <PageHeader title="Settings" description="Your organization, workspaces, and projects." />
      {(wFailed || ctx.degraded) && <DegradedNote what="Some settings" />}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader><Eyebrow>Organization</Eyebrow></CardHeader>
          <CardBody className="space-y-3">
            <Row label="Slug" value={<Value>{ctx.session.orgSlug}</Value>} />
            <Row label="Org ID" value={<Value className="text-xs text-muted">{ctx.session.orgId}</Value>} />
            <Row label="Signed in as" value={<span className="text-[13px]">{ctx.session.email}</span>} />
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="flex items-center justify-between">
            <Eyebrow>Workspaces &amp; projects</Eyebrow>
            <div className="flex gap-2">
              <CreateWorkspace />
              <CreateProject workspaces={workspaces.map((w) => ({ id: w.id, name: w.name }))} />
            </div>
          </CardHeader>
          <CardBody>
            {workspaces.length === 0 ? (
              <EmptyState
                title="No workspaces yet"
                description="Create a workspace, then a project inside it, to start registering verifiers."
              />
            ) : (
              <div className="space-y-5">
                {workspaces.map((w) => {
                  const projects = projectsByWs.get(w.id) ?? [];
                  return (
                    <div key={w.id}>
                      <div className="flex items-baseline justify-between">
                        <h3 className="text-sm font-semibold text-ink">{w.name}</h3>
                        <Value className="text-2xs text-faint">{w.slug}</Value>
                      </div>
                      {projects.length === 0 ? (
                        <p className="mt-1 text-[13px] text-muted">No projects in this workspace.</p>
                      ) : (
                        <ul className="mt-2 divide-y divide-line rounded-md border border-line">
                          {projects.map((p) => (
                            <li key={p.id} className="flex items-center justify-between px-3 py-2">
                              <span>
                                <span className="text-[13px] font-medium text-ink">{p.name}</span>
                                {p.description && <span className="ml-2 text-2xs text-faint">{p.description}</span>}
                              </span>
                              <Value className="text-2xs text-faint">{p.slug}</Value>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-2xs font-medium uppercase tracking-wider text-faint">{label}</span>
      {value}
    </div>
  );
}
