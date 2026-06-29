import * as React from "react";

import { Badge } from "./primitives";
import { statusTone, titleCase, SEVERITY_COLOR } from "@/lib/format";
import type { EvaluationStatus, Severity, VerificationStatus } from "@/lib/api/types";

export function StatusBadge({ status }: { status: VerificationStatus | EvaluationStatus }) {
  const tone = statusTone(status);
  return <Badge tone={tone} dot>{titleCase(status)}</Badge>;
}

export function VerdictBadge({ passed }: { passed: boolean | null }) {
  if (passed === null || passed === undefined) return <span className="text-faint">—</span>;
  return passed ? <Badge tone="pass">Passed</Badge> : <Badge tone="risk">Failed</Badge>;
}

const SEV_TONE: Record<Severity, "crit" | "risk" | "warn" | "muted"> = {
  critical: "crit", high: "risk", medium: "warn", low: "muted",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEV_TONE[severity]}>{titleCase(severity)}</Badge>;
}

export { SEVERITY_COLOR };
