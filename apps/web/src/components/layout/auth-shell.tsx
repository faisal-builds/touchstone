import Link from "next/link";
import * as React from "react";

/**
 * The auth split layout. The left panel states the product thesis with the
 * assay-streak motif; the right hosts the form. Kept deliberately quiet so the
 * single gold streak is the memorable element.
 */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Thesis panel */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-ink p-12 text-paper lg:flex">
        <span className="streak absolute left-0 top-0 h-[3px] w-full" />
        <Link href="/" className="flex items-center gap-2.5">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <path d="M9 22 L20 9" stroke="url(#lg)" strokeWidth="3" strokeLinecap="round" />
            <circle cx="22" cy="22" r="2.4" fill="#D9A94A" />
            <defs>
              <linearGradient id="lg" x1="9" y1="22" x2="20" y2="9" gradientUnits="userSpaceOnUse">
                <stop stopColor="#8A5A1C" /><stop offset="1" stopColor="#D9A94A" />
              </linearGradient>
            </defs>
          </svg>
          <span className="text-[15px] font-semibold tracking-tight2">Touchstone</span>
        </Link>
        <div className="max-w-md">
          <p className="eyebrow text-assay-to">The verification layer for AI</p>
          <h2 className="mt-3 text-3xl font-semibold leading-tight tracking-tight2">
            Test the verifier before you trust the verdict.
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-paper/70">
            A touchstone reveals the purity of gold by the streak it leaves. Touchstone
            does the same for AI judgment — grading artifacts, scoring risk, recording
            every decision in a tamper-evident chain, and measuring how robust each
            verifier is against manipulation.
          </p>
        </div>
        <dl className="grid grid-cols-3 gap-6 text-paper/80">
          {[
            ["Verifiers", "graded in a sandbox"],
            ["Robustness", "scored with CIs"],
            ["Audit", "hash-chained"],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[13px] font-medium text-paper">{k}</dt>
              <dd className="mt-0.5 text-2xs text-paper/55">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
      {/* Form panel */}
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-7">
            <h1 className="text-2xl font-semibold tracking-tight2 text-ink">{title}</h1>
            <p className="mt-1 text-sm text-muted">{subtitle}</p>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
