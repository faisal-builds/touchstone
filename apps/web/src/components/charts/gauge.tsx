"use client";

import * as React from "react";

import { BAND_LABEL, robustnessBand, type Band } from "@/lib/format";

/**
 * The Robustness Gauge — the product's signature element. A semicircular dial
 * whose arc is the "assay streak" (bronze→gold), with the score in large tabular
 * monospace. The confidence interval is drawn as a faint band on the track.
 */

const BAND_STROKE: Record<Band, string> = {
  strong: "#2F7D5B",
  fair: "#B5832B",
  weak: "#C2533B",
  unknown: "#9AA0A8",
};

function polar(cx: number, cy: number, r: number, frac: number): [number, number] {
  // frac 0..1 maps left (180°) → right (0°) over the top.
  const angle = Math.PI - frac * Math.PI;
  return [cx + r * Math.cos(angle), cy - r * Math.sin(angle)];
}

export function RobustnessGauge({
  value,
  ci,
  size = 220,
  label = true,
}: {
  value: number | null | undefined;
  ci?: { low: number; high: number } | null;
  size?: number;
  label?: boolean;
}) {
  const w = size;
  const h = size * 0.62;
  const stroke = size * 0.07;
  const cx = w / 2;
  const cy = h - stroke;
  const r = w / 2 - stroke;
  const arcLen = Math.PI * r;

  const v = value === null || value === undefined || Number.isNaN(value) ? 0 : value;
  const band = robustnessBand(value);
  const hasValue = value !== null && value !== undefined && !Number.isNaN(value);

  const track = `M ${cx - r},${cy} A ${r},${r} 0 0 1 ${cx + r},${cy}`;
  const gradId = React.useId();

  // CI band endpoints on the track.
  const ciFrom = ci ? polar(cx, cy, r, Math.max(0, ci.low)) : null;
  const ciTo = ci ? polar(cx, cy, r, Math.min(1, ci.high)) : null;

  return (
    <div className="flex flex-col items-center">
      <svg width={w} height={h + 4} viewBox={`0 0 ${w} ${h + 4}`} role="img"
        aria-label={`Robustness ${hasValue ? (v * 100).toFixed(1) + " percent" : "not evaluated"}`}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#8A5A1C" />
            <stop offset="100%" stopColor="#D9A94A" />
          </linearGradient>
        </defs>
        {/* Track */}
        <path d={track} fill="none" stroke="#EAEAE4" strokeWidth={stroke} strokeLinecap="round" />
        {/* CI band (faint) */}
        {ciFrom && ciTo && (
          <path
            d={`M ${ciFrom[0]},${ciFrom[1]} A ${r},${r} 0 0 1 ${ciTo[0]},${ciTo[1]}`}
            fill="none" stroke={BAND_STROKE[band]} strokeOpacity={0.18}
            strokeWidth={stroke} strokeLinecap="butt"
          />
        )}
        {/* Value arc — the assay streak */}
        {hasValue && (
          <path
            d={track} fill="none" stroke={`url(#${gradId})`} strokeWidth={stroke}
            strokeLinecap="round" strokeDasharray={`${arcLen} ${arcLen}`}
            strokeDashoffset={arcLen * (1 - v)}
          />
        )}
      </svg>
      <div className="-mt-[34%] flex flex-col items-center">
        <span className="data text-3xl font-semibold tracking-tight2 text-ink">
          {hasValue ? (v * 100).toFixed(1) : "—"}
          {hasValue && <span className="text-base text-faint">%</span>}
        </span>
        {label && (
          <span
            className="mt-0.5 text-2xs font-semibold uppercase tracking-wider"
            style={{ color: BAND_STROKE[band] }}
          >
            {BAND_LABEL[band]}
          </span>
        )}
      </div>
    </div>
  );
}
