import { SkeletonCards, SkeletonTable } from "@/components/ui/states";

export default function Loading() {
  return (
    <div className="animate-fade-in">
      <div className="mb-6 h-8 w-48 skeleton rounded" />
      <SkeletonCards count={4} />
      <div className="mt-6">
        <SkeletonTable rows={6} />
      </div>
    </div>
  );
}
