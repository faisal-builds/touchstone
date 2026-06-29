"use client";

import { ErrorState } from "@/components/ui/states";
import { Button } from "@/components/ui/primitives";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="py-10">
      <ErrorState
        title="Something went wrong on this page"
        detail={error.message || "An unexpected error occurred while loading this view."}
        retry={<Button variant="secondary" onClick={reset}>Try again</Button>}
      />
    </div>
  );
}
