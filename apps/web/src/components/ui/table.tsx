import * as React from "react";

import { cn } from "@/lib/cn";

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface shadow-card">
      <table className={cn("w-full border-collapse text-sm", className)} {...props} />
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="border-b border-line bg-paper/60">
      <tr>{children}</tr>
    </thead>
  );
}

export function TH({
  className,
  children,
  align = "left",
}: {
  className?: string;
  children?: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cn(
        "px-4 py-2.5 text-2xs font-semibold uppercase tracking-wider text-faint",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TBody({ children }: { children: React.ReactNode }) {
  return <tbody className="divide-y divide-line">{children}</tbody>;
}

export function TR({
  className,
  children,
  onClick,
}: {
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <tr
      onClick={onClick}
      className={cn("group transition-colors", onClick && "cursor-pointer hover:bg-paper", className)}
    >
      {children}
    </tr>
  );
}

export function TD({
  className,
  children,
  align = "left",
}: {
  className?: string;
  children?: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <td
      className={cn(
        "px-4 py-3 align-middle text-ink",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </td>
  );
}

// --- StatCard ----------------------------------------------------------------

export function StatCard({
  label,
  value,
  sub,
  accent,
  children,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-line bg-surface p-5 shadow-card">
      {accent && <span className="streak absolute inset-x-0 top-0 h-[2px]" />}
      <p className="text-2xs font-medium uppercase tracking-wider text-faint">{label}</p>
      <div className="mt-2 text-2xl font-semibold tracking-tight2 text-ink data">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}
