"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Input, Textarea } from "@/components/ui/form";
import { Button } from "@/components/ui/primitives";

const DEFAULT_CASES = JSON.stringify(
  [
    { artifact: { answer: 42, explanation: "the meaning" }, should_pass: true },
    { artifact: { answer: 0 }, should_pass: false },
  ],
  null,
  2,
);

export function LaunchEvaluation({ verifierId }: { verifierId: string }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [seed, setSeed] = React.useState("1337");
  const [maxAttacks, setMaxAttacks] = React.useState("200");
  const [cases, setCases] = React.useState(DEFAULT_CASES);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit() {
    setError(null);
    let seedCases: unknown;
    try {
      seedCases = JSON.parse(cases);
      if (!Array.isArray(seedCases)) throw new Error();
    } catch {
      setError("Seed cases must be a JSON array of { artifact, should_pass }.");
      return;
    }
    setBusy(true);
    const res = await fetch("/api/rhd/v1/robustness/evaluations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        verifier_id: verifierId,
        seed_cases: seedCases,
        seed: Number(seed) || 1337,
        max_attacks: Number(maxAttacks) || 200,
      }),
    });
    setBusy(false);
    if (res.ok) {
      setOpen(false);
      router.refresh();
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Couldn't launch the evaluation.");
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>Launch evaluation</Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Launch a robustness evaluation"
        description="Touchstone attacks this verifier with adversarial artifacts that should not pass, then scores how often it was fooled."
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy}>{busy ? "Launching…" : "Launch"}</Button>
          </>
        }
      >
        <div className="space-y-4">
          <FormError>{error}</FormError>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Seed" hint="reproducible">
              <Input mono value={seed} onChange={(e) => setSeed(e.target.value)} />
            </Field>
            <Field label="Max attacks">
              <Input mono value={maxAttacks} onChange={(e) => setMaxAttacks(e.target.value)} />
            </Field>
          </div>
          <Field label="Seed cases" hint="labeled artifacts to mutate (JSON)">
            <Textarea mono rows={8} value={cases}
              onChange={(e) => setCases(e.target.value)} spellCheck={false} />
          </Field>
          <p className="text-xs text-muted">
            The evaluation runs in the background. This page will show it as pending,
            then completed with a robustness score and any exploits found.
          </p>
        </div>
      </Dialog>
    </>
  );
}
