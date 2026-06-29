import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/ui/states";
import { Button } from "@/components/ui/primitives";

/** Shown on data pages when the org has no project selected yet. */
export function NoProject() {
  return (
    <EmptyState
      title="No project selected"
      description="Projects hold your verifiers, runs, and robustness evaluations. Create one to get started."
      action={
        <Link href="/settings">
          <Button>Go to settings</Button>
        </Link>
      }
    />
  );
}

/** A quiet banner when a backend couldn't be reached, so a partial page is honest. */
export function DegradedNote({ what = "Some data" }: { what?: string }) {
  return (
    <div className="mb-4 rounded-md border border-warn/25 bg-warn/[0.05] px-3 py-2 text-[13px] text-warn">
      {what} couldn&apos;t be loaded right now. The view below may be incomplete.
    </div>
  );
}
