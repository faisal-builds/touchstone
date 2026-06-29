/**
 * Pure presentation helpers — formatting and the mapping from domain values to
 * the design system's semantic vocabulary. No I/O, so these are exhaustively
 * unit-tested.
 */

import type { Severity, VerificationStatus, EvaluationStatus } from "./api/types";

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function score(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function shortHash(hash: string | null | undefined, head = 8): string {
  if (!hash) return "—";
  return hash.length <= head ? hash : `${hash.slice(0, head)}…`;
}

export function shortId(id: string | null | undefined): string {
  return shortHash(id, 8);
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Math.round((now - then) / 1000);
  if (diff < 0) return "just now";
  if (diff < 60) return `${diff}s ago`;
  const m = Math.floor(diff / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

/** Robustness band: the qualitative read of a robustness score. */
export type Band = "strong" | "fair" | "weak" | "unknown";

export function robustnessBand(value: number | null | undefined): Band {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  if (value >= 0.9) return "strong";
  if (value >= 0.7) return "fair";
  return "weak";
}

export const BAND_LABEL: Record<Band, string> = {
  strong: "Robust",
  fair: "Fair",
  weak: "Gameable",
  unknown: "Not evaluated",
};

/** Tailwind text/border tokens by band — used for the gauge and badges. */
export const BAND_COLOR: Record<Band, string> = {
  strong: "text-pass",
  fair: "text-warn",
  weak: "text-risk",
  unknown: "text-faint",
};

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0, high: 1, medium: 2, low: 3,
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "text-crit",
  high: "text-risk",
  medium: "text-warn",
  low: "text-muted",
};

export function statusTone(
  status: VerificationStatus | EvaluationStatus,
): "pass" | "warn" | "risk" | "muted" {
  switch (status) {
    case "completed": return "pass";
    case "running": return "warn";
    case "pending": return "muted";
    case "failed": return "risk";
    default: return "muted";
  }
}

/** Risk band from a 0..1 risk score (higher = riskier). */
export function riskBand(value: number | null | undefined): Band {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  if (value >= 0.6) return "weak"; // high risk
  if (value >= 0.3) return "fair";
  return "strong"; // low risk
}

const CATEGORY_LABELS: Record<string, string> = {
  content_corruption: "Content corruption",
  judge_manipulation: "Judge manipulation",
  length_bias: "Length bias",
  formatting_exploit: "Formatting exploit",
  edge_case: "Edge case",
  model_generated: "Model-generated",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
