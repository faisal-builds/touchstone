"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { CopyButton } from "@/components/ui/copy";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Select } from "@/components/ui/form";
import { Button } from "@/components/ui/primitives";
import { IconPlus } from "@/components/ui/icons";
import type { ApiKeyCreated, Project } from "@/lib/api/types";

export function CreateApiKey({ projects }: { projects: Pick<Project, "id" | "name">[] }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [role, setRole] = React.useState("service");
  const [projectId, setProjectId] = React.useState("");
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  function reset() {
    setOpen(false);
    setName("");
    setRole("service");
    setProjectId("");
    setCreated(null);
    setError(null);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    const res = await fetch("/api/cp/v1/api-keys", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, role, project_id: projectId || null }),
    });
    setBusy(false);
    if (res.ok) {
      setCreated((await res.json()) as ApiKeyCreated);
      router.refresh();
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Couldn't create the key.");
  }

  const fullKey = created
    ? `tsk_${created.key_id}_${created.secret}`
    : "";

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <IconPlus /> Create key
      </Button>
      <Dialog
        open={open}
        onClose={reset}
        title={created ? "Save your API key" : "Create an API key"}
        description={
          created
            ? "This secret is shown only once. Store it somewhere safe."
            : "Keys authenticate the SDK and CI against your organization."
        }
        footer={
          created ? (
            <Button onClick={reset}>Done</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={reset}>Cancel</Button>
              <Button onClick={submit} disabled={busy || !name}>
                {busy ? "Creating…" : "Create key"}
              </Button>
            </>
          )
        }
      >
        {created ? (
          <div className="space-y-3">
            <div className="rounded-md border border-assay/30 bg-assay/[0.04] p-3">
              <p className="mb-1.5 text-2xs font-medium uppercase tracking-wider text-assay">Secret key</p>
              <div className="flex items-center gap-2">
                <code className="data flex-1 break-all rounded bg-surface px-2 py-1.5 text-[12px] text-ink">
                  {fullKey}
                </code>
                <CopyButton value={fullKey} label="Copy" />
              </div>
            </div>
            <p className="text-[13px] text-muted">
              Use it as a bearer token: <code className="data">Authorization: Bearer {`{key}`}</code>.
              You won&apos;t be able to see it again.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <FormError>{error}</FormError>
            <Field label="Name" hint="how you'll recognize it">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="CI pipeline" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Role">
                <Select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="service">Service</option>
                  <option value="viewer">Viewer</option>
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </Select>
              </Field>
              <Field label="Project" hint="optional scope">
                <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                  <option value="">Whole organization</option>
                  {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </Field>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
