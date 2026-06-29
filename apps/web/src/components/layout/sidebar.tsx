"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { cn } from "@/lib/cn";
import {
  IconAudit, IconExploit, IconKey, IconOverview, IconRisk, IconRobustness,
  IconRuns, IconSettings, IconVerifier,
} from "@/components/ui/icons";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}
interface NavGroup {
  label?: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  { items: [{ href: "/dashboard", label: "Overview", icon: IconOverview }] },
  {
    label: "Verify",
    items: [
      { href: "/verifiers", label: "Verifiers", icon: IconVerifier },
      { href: "/verifications", label: "Runs", icon: IconRuns },
      { href: "/risk", label: "Risk", icon: IconRisk },
    ],
  },
  {
    label: "Assurance",
    items: [
      { href: "/robustness", label: "Robustness", icon: IconRobustness },
      { href: "/exploits", label: "Exploit corpus", icon: IconExploit },
      { href: "/audit", label: "Audit trail", icon: IconAudit },
    ],
  },
  {
    label: "Operations",
    items: [
      { href: "/operations", label: "Inline plane", icon: IconRisk },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/api-keys", label: "API keys", icon: IconKey },
      { href: "/settings", label: "Settings", icon: IconSettings },
    ],
  },
];

export function Brand() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2.5 px-2">
      <span className="flex h-7 w-7 items-center justify-center rounded-[7px] bg-ink">
        <svg width="16" height="16" viewBox="0 0 32 32" aria-hidden>
          <path d="M9 22 L20 9" stroke="url(#bg)" strokeWidth="3" strokeLinecap="round" />
          <circle cx="22" cy="22" r="2.4" fill="#D9A94A" />
          <defs>
            <linearGradient id="bg" x1="9" y1="22" x2="20" y2="9" gradientUnits="userSpaceOnUse">
              <stop stopColor="#8A5A1C" /><stop offset="1" stopColor="#D9A94A" />
            </linearGradient>
          </defs>
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight2 text-ink">Touchstone</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <nav className="flex h-full flex-col gap-6 px-3 py-5">
      <div className="px-1">
        <Brand />
      </div>
      <div className="flex flex-1 flex-col gap-5">
        {GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && (
              <p className="mb-1 px-3 text-2xs font-semibold uppercase tracking-[0.12em] text-faint">
                {group.label}
              </p>
            )}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.href} className="relative">
                    {active && (
                      <span className="streak-v absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full" />
                    )}
                    <Link
                      href={item.href}
                      className={cn(
                        "flex items-center gap-2.5 rounded-md px-3 py-[7px] text-[13.5px] transition-colors",
                        active
                          ? "bg-line/60 font-medium text-ink"
                          : "text-muted hover:bg-line/40 hover:text-ink",
                      )}
                    >
                      <Icon className={cn(active ? "text-assay" : "text-faint")} />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
