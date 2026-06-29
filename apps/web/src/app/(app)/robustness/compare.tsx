"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Eyebrow, Value } from "@/components/ui/primitives";
import { Field, Select } from "@/components/ui/form";
import type { Comparison, Evaluation } from "@/lib/api/types";
import { pct, shortId } from "@/lib/format";

export function CompareEvaluations({ evaluations }: { evaluations: Evaluation[] }) {
  const completed = evaluations.filter((e) => e.status === "completed");
  const [baseline, setBaseline] = React.useState(completed[0]?.id ?? "");
  const [candidate, setCandidate] = React.useState(completed[1]?.id ?? completed[0]?.id ?? "");
  const [result, setResult] = React.useState<Comparison | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  if (completed.length < 2) {
    return (
      <Card>
        <CardHeader><Eyebrow>Compare versions</Eyebrow></CardHeader>
        <CardBody>
          <p className="text-sm text-muted">
            Run at least two evaluations to compare robustness across versions and detect regressions.
          </p>
        </CardBody>
      </Card>
    );
  }

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    const res = await fetch("/api/rhd/v1/robustness/compare", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ baseline_evaluation_id: baseline, candidate_evaluation_id: candidate }),
    });
    setBusy(false);
    if (res.ok) {
      setResult((await res.json()) as Comparison);
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Couldn't compare those evaluations.");
  }

  const label = (e: Evaluation) => `${shortId(e.id)} · v${e.verifier_version} · ${pct(e.robustness_score, 0)}`;

  return (
    <Card>
      <CardHeader><Eyebrow>Compare versions</Eyebrow></CardHeader>
      <CardBody>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field label="Baseline">
            <Select value={baseline} onChange={(e) => setBaseline(e.target.value)}>
              {completed.map((e) => <option key={e.id} value={e.id}>{label(e)}</option>)}
            </Select>
          </Field>
          <Field label="Candidate">
            <Select value={candidate} onChange={(e) => setCandidate(e.target.value)}>
              {completed.map((e) => <option key={e.id} value={e.id}>{label(e)}</option>)}
            </Select>
          </Field>
          <Button onClick={run} disabled={busy || baseline === candidate}>
            {busy ? "Comparing…" : "Compare"}
          </Button>
        </div>

        {error && <p className="mt-3 text-[13px] text-risk">{error}</p>}

        {result && (
          <div className="mt-4 flex flex-wrap items-center gap-6 rounded-lg border border-line bg-paper px-4 py-3">
            <div>
              <p className="text-2xs uppercase tracking-wider text-faint">Baseline</p>
              <Value className="text-lg font-semibold">{pct(result.baseline_robustness)}</Value>
            </div>
            <div className="text-faint">→</div>
            <div>
              <p className="text-2xs uppercase tracking-wider text-faint">Candidate</p>
              <Value className="text-lg font-semibold">{pct(result.candidate_robustness)}</Value>
            </div>
            <div>
              <p className="text-2xs uppercase tracking-wider text-faint">Δ</p>
              <Value className={`text-lg font-semibold ${result.delta < 0 ? "text-risk" : "text-pass"}`}>
                {result.delta >= 0 ? "+" : ""}{pct(result.delta)}
              </Value>
            </div>
            <div className="ml-auto">
              {result.is_regression
                ? <Badge tone="risk" dot>Regression</Badge>
                : result.is_improvement
                  ? <Badge tone="pass" dot>Improvement</Badge>
                  : <Badge tone="muted" dot>No meaningful change</Badge>}
              <p className="mt-1 text-2xs text-faint">{result.detail}</p>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
