"use client";

import * as React from "react";

import { IconCheck, IconCopy } from "./icons";

export function CopyButton({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = React.useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (e.g. insecure context) — no-op.
    }
  }
  return (
    <button
      onClick={copy}
      className="inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 py-1 text-2xs font-medium text-muted transition-colors hover:text-ink"
      aria-label={`Copy ${label || "value"}`}
    >
      {copied ? <IconCheck className="text-pass" /> : <IconCopy />}
      {copied ? "Copied" : label || "Copy"}
    </button>
  );
}
