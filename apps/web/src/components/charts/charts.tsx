import * as React from "react";

import { cn } from "@/lib/cn";
import { categoryLabel } from "@/lib/format";

/** A labeled horizontal bar — used for category/severity distributions. */
export function BarRow({
  label,
  value,
  max,
  tone = "#23262D",
  suffix,
}: {
  label: string;
  value: number;
  max: number;
  tone?: string;
  suffix?: string;
}) {
  const w = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-40 shrink-0 truncate text-[13px] text-muted">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-line/70">
        <div className="h-full rounded-full" style={{ width: `${w}%`, background: tone }} />
      </div>
      <span className="data w-12 shrink-0 text-right text-xs text-ink">
        {value}
        {suffix}
      </span>
    </div>
  );
}

const CATEGORY_TONE: Record<string, string> = {
  content_corruption: "#9B2D2D",
  judge_manipulation: "#C2533B",
  length_bias: "#B5832B",
  formatting_exploit: "#3A6491",
  edge_case: "#6B7280",
  model_generated: "#23262D",
};

export function CategoryBreakdown({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = entries.reduce((m, [, v]) => Math.max(m, v), 0);
  if (entries.length === 0) {
    return <p className="text-sm text-muted">No exploits in this evaluation.</p>;
  }
  return (
    <div>
      {entries.map(([cat, v]) => (
        <BarRow
          key={cat}
          label={categoryLabel(cat)}
          value={v}
          max={max}
          tone={CATEGORY_TONE[cat] ?? "#23262D"}
        />
      ))}
    </div>
  );
}

/** A compact robustness sparkline (oldest → newest). */
export function Sparkline({
  data,
  width = 160,
  height = 40,
}: {
  data: number[];
  width?: number;
  height?: number;
}) {
  if (data.length < 2) {
    return <span className="text-xs text-faint">Not enough history</span>;
  }
  const pad = 3;
  const xs = (i: number) => pad + (i / (data.length - 1)) * (width - pad * 2);
  const ys = (v: number) => height - pad - v * (height - pad * 2);
  const d = data.map((v, i) => `${i === 0 ? "M" : "L"} ${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(" ");
  const last = data[data.length - 1] ?? 0;
  const first = data[0] ?? 0;
  const up = last >= first;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
      <path d={d} fill="none" stroke={up ? "#2F7D5B" : "#C2533B"} strokeWidth={1.5}
        strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={xs(data.length - 1)} cy={ys(last)} r={2.5} fill={up ? "#2F7D5B" : "#C2533B"} />
    </svg>
  );
}

/** A thin stacked severity bar (critical → low). */
export function SeverityStrip({
  counts,
  className,
}: {
  counts: Partial<Record<"critical" | "high" | "medium" | "low", number>>;
  className?: string;
}) {
  const order: Array<["critical" | "high" | "medium" | "low", string]> = [
    ["critical", "#9B2D2D"],
    ["high", "#C2533B"],
    ["medium", "#B5832B"],
    ["low", "#9AA0A8"],
  ];
  const total = order.reduce((s, [k]) => s + (counts[k] ?? 0), 0);
  if (total === 0) {
    return <div className={cn("h-2 w-full rounded-full bg-line/70", className)} />;
  }
  return (
    <div className={cn("flex h-2 w-full overflow-hidden rounded-full", className)}>
      {order.map(([k, color]) => {
        const v = counts[k] ?? 0;
        if (v === 0) return null;
        return <div key={k} style={{ width: `${(v / total) * 100}%`, background: color }} />;
      })}
    </div>
  );
}
