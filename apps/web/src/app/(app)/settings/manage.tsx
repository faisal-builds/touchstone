"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Select } from "@/components/ui/form";
import { Button } from "@/components/ui/primitives";
import { IconPlus } from "@/components/ui/icons";

function slugify(s: string): string {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

export function CreateWorkspace() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    const res = await fetch("/api/cp/v1/workspaces", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, slug: slugify(name) }),
    });
    setBusy(false);
    if (res.ok) { setOpen(false); setName(""); router.refresh(); return; }
    const b = await res.json().catch(() => ({}));
    setError(b.detail || b.title || "Couldn't create the workspace.");
  }

  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}><IconPlus /> Workspace</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Create a workspace"
        description="Workspaces group related projects."
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !name}>{busy ? "Creating…" : "Create"}</Button></>}>
        <div className="space-y-4">
          <FormError>{error}</FormError>
          <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Research" /></Field>
        </div>
      </Dialog>
    </>
  );
}

export function CreateProject({ workspaces }: { workspaces: { id: string; name: string }[] }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [workspaceId, setWorkspaceId] = React.useState(workspaces[0]?.id ?? "");
  const [description, setDescription] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/cp/v1/workspaces/${workspaceId}/projects`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, slug: slugify(name), description: description || null }),
    });
    setBusy(false);
    if (res.ok) { setOpen(false); setName(""); setDescription(""); router.refresh(); return; }
    const b = await res.json().catch(() => ({}));
    setError(b.detail || b.title || "Couldn't create the project.");
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} disabled={workspaces.length === 0}><IconPlus /> Project</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Create a project"
        description="Projects hold verifiers, runs, and robustness evaluations."
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !name || !workspaceId}>{busy ? "Creating…" : "Create"}</Button></>}>
        <div className="space-y-4">
          <FormError>{error}</FormError>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Math grader" /></Field>
            <Field label="Workspace">
              <Select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
                {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          </div>
          <Field label="Description" hint="optional">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Grades competition math solutions" />
          </Field>
        </div>
      </Dialog>
    </>
  );
}
