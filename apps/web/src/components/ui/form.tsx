import * as React from "react";

import { cn } from "@/lib/cn";

const FIELD_BASE =
  "w-full rounded-md border border-line-strong bg-surface px-3 text-sm text-ink " +
  "placeholder:text-faint transition-colors focus-visible:border-assay focus-visible:shadow-focus " +
  "disabled:opacity-50";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }
>(({ className, mono, ...props }, ref) => (
  <input ref={ref} className={cn(FIELD_BASE, "h-9", mono && "data", className)} {...props} />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { mono?: boolean }
>(({ className, mono, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(FIELD_BASE, "py-2 leading-relaxed", mono && "data", className)}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn(FIELD_BASE, "h-9 pr-8", className)} {...props} />
));
Select.displayName = "Select";

export function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="block">
      <span className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        {hint && <span className="text-2xs text-faint">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function FormError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return (
    <p className="rounded-md border border-risk/25 bg-risk/[0.04] px-3 py-2 text-[13px] text-risk">
      {children}
    </p>
  );
}
