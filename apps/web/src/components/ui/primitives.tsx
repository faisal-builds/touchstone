import * as React from "react";

import { cn } from "@/lib/cn";

// --- Button -----------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-md font-medium " +
  "transition-colors disabled:cursor-not-allowed disabled:opacity-50 " +
  "focus-visible:shadow-focus select-none";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-graphite text-paper hover:bg-ink",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-paper hover:border-faint",
  ghost: "bg-transparent text-muted hover:text-ink hover:bg-line/50",
  danger: "bg-surface text-crit border border-crit/30 hover:bg-crit/5",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-9 px-4 text-sm",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(BUTTON_BASE, BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

// --- Card --------------------------------------------------------------------

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-lg border border-line bg-surface shadow-card", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pt-4 pb-3 border-b border-line", className)} {...props} />;
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />;
}

// --- Badge -------------------------------------------------------------------

type Tone = "pass" | "warn" | "risk" | "crit" | "muted" | "info";

const BADGE_TONES: Record<Tone, string> = {
  pass: "text-pass bg-pass/8 border-pass/20",
  warn: "text-warn bg-warn/8 border-warn/20",
  risk: "text-risk bg-risk/8 border-risk/20",
  crit: "text-crit bg-crit/8 border-crit/25",
  muted: "text-muted bg-line/50 border-line-strong",
  info: "text-info bg-info/8 border-info/20",
};

export function Badge({
  tone = "muted",
  dot = false,
  className,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-2xs font-medium",
        BADGE_TONES[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

// --- Value (mono data) -------------------------------------------------------

export function Value({
  className,
  mono = true,
  children,
}: {
  className?: string;
  mono?: boolean;
  children: React.ReactNode;
}) {
  return <span className={cn(mono && "data", className)}>{children}</span>;
}

// --- Eyebrow + PageHeader ----------------------------------------------------

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="eyebrow">{children}</p>;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 pb-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight2 text-ink">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
