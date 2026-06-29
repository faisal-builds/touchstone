import Link from "next/link";

import { Button } from "@/components/ui/primitives";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <p className="data text-5xl font-semibold tracking-tight2 text-ink">404</p>
      <p className="mt-2 text-sm text-muted">We couldn&apos;t find that. It may have been moved or removed.</p>
      <Link href="/dashboard" className="mt-5"><Button>Back to overview</Button></Link>
    </div>
  );
}
