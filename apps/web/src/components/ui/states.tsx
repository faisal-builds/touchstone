import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * The three states every data surface must handle. Per the design brief, empty
 * states are an invitation to act and errors say what happened and how to fix it
 * — never an apology, always in the interface's voice.
 */

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line-strong bg-surface px-6 py-14 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({
  title = "Couldn't load this",
  detail,
  retry,
}: {
  title?: string;
  detail?: string;
  retry?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-risk/25 bg-risk/[0.03] px-6 py-12 text-center">
      <div className="mb-2 flex h-8 w-8 items-center justify-center rounded-full border border-risk/30 text-risk">
        !
      </div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {detail && <p className="mt-1 max-w-md text-sm text-muted">{detail}</p>}
      {retry && <div className="mt-4">{retry}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4 w-full", className)} />;
}

export function SkeletonTable({ rows = 6 }: { rows?: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="border-b border-line px-4 py-3">
        <Skeleton className="h-3.5 w-32" />
      </div>
      <div className="divide-y divide-line">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3.5">
            <Skeleton className="h-3.5 w-1/4" />
            <Skeleton className="h-3.5 w-1/5" />
            <Skeleton className="ml-auto h-3.5 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-line bg-surface p-5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-4 h-7 w-24" />
        </div>
      ))}
    </div>
  );
}
