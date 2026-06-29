"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/form";
import { Button } from "@/components/ui/primitives";
import { IconPlus } from "@/components/ui/icons";

const TEMPLATES: { code: string; model: string; process: string; hybrid: string } = {
  code: JSON.stringify(
    {
      code: "def check(artifact):\n    ok = isinstance(artifact, dict) and artifact.get('answer') == 42\n    return {'score': 1.0 if ok else 0.0}",
      threshold: 1.0,
    },
    null,
    2,
  ),
  model: JSON.stringify({ model: "mock", rubric: "Award 1.0 only if the answer is correct and complete.", threshold: 0.7 }, null, 2),
  process: JSON.stringify({ steps: [{ name: "exit-code", expect: 0 }], threshold: 1.0 }, null, 2),
  hybrid: JSON.stringify({ members: [{ type: "code", code: "def check(a):\n    return {'score': 1.0}" }], weights: [1.0], threshold: 0.7 }, null, 2),
};

function slugify(s: string): string {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

export function RegisterVerifier({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [type, setType] = React.useState("code");
  const [definition, setDefinition] = React.useState(TEMPLATES.code);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  function pickType(t: string) {
    setType(t);
    setDefinition(TEMPLATES[t as keyof typeof TEMPLATES] ?? "{}");
  }

  async function submit() {
    setError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(definition);
    } catch {
      setError("The definition isn't valid JSON.");
      return;
    }
    setBusy(true);
    const res = await fetch(`/api/cp/v1/projects/${projectId}/verifiers`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, slug: slugify(name), verifier_type: type, definition: parsed }),
    });
    setBusy(false);
    if (res.ok) {
      setOpen(false);
      setName("");
      router.refresh();
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Couldn't register the verifier.");
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <IconPlus /> Register verifier
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Register a verifier"
        description="Define how artifacts are graded. Registering creates version 1; re-registering the same slug bumps the version."
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy || !name}>
              {busy ? "Registering…" : "Register"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <FormError>{error}</FormError>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Answer checker" />
            </Field>
            <Field label="Type">
              <Select value={type} onChange={(e) => pickType(e.target.value)}>
                <option value="code">Code</option>
                <option value="model">Model judge</option>
                <option value="process">Process</option>
                <option value="hybrid">Hybrid ensemble</option>
              </Select>
            </Field>
          </div>
          <Field label="Definition" hint="JSON">
            <Textarea mono rows={10} value={definition}
              onChange={(e) => setDefinition(e.target.value)} spellCheck={false} />
          </Field>
        </div>
      </Dialog>
    </>
  );
}
