"use client";

import * as React from "react";

import { Button } from "@/components/ui/primitives";

export function DownloadReport({ evalId }: { evalId: string }) {
  const [busy, setBusy] = React.useState(false);
  async function download() {
    setBusy(true);
    try {
      const res = await fetch(`/api/rhd/v1/robustness/evaluations/${evalId}/report`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `robustness-report-${evalId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button variant="secondary" onClick={download} disabled={busy}>
      {busy ? "Preparing…" : "Export report"}
    </Button>
  );
}
