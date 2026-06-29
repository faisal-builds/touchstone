import * as React from "react";

/** Minimal 20px line icons (1.6 stroke, currentColor). Kept inline to avoid a
 * dependency and to keep the visual language consistent. */

type P = React.SVGProps<SVGSVGElement>;

function Icon({ children, ...p }: P & { children: React.ReactNode }) {
  return (
    <svg
      width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden {...p}
    >
      {children}
    </svg>
  );
}

export const IconOverview = (p: P) => (
  <Icon {...p}><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></Icon>
);
export const IconVerifier = (p: P) => (
  <Icon {...p}><path d="M12 3l7 3v5c0 4-3 7-7 9-4-2-7-5-7-9V6z" /><path d="M9 12l2 2 4-4" /></Icon>
);
export const IconRuns = (p: P) => (
  <Icon {...p}><path d="M5 12h14" /><path d="M5 6h14" /><path d="M5 18h9" /><circle cx="18" cy="18" r="2.5" /></Icon>
);
export const IconRisk = (p: P) => (
  <Icon {...p}><path d="M12 3l9 16H3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></Icon>
);
export const IconRobustness = (p: P) => (
  <Icon {...p}><path d="M4 14a8 8 0 0 1 16 0" /><path d="M12 14l4-4" /><circle cx="12" cy="14" r="1.2" /></Icon>
);
export const IconExploit = (p: P) => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></Icon>
);
export const IconAudit = (p: P) => (
  <Icon {...p}><circle cx="7" cy="6" r="2" /><circle cx="7" cy="18" r="2" /><path d="M7 8v8" /><path d="M11 6h8M11 18h6" /></Icon>
);
export const IconKey = (p: P) => (
  <Icon {...p}><circle cx="8" cy="8" r="4" /><path d="M11 11l8 8" /><path d="M16 16l2-2M19 19l1.5-1.5" /></Icon>
);
export const IconSettings = (p: P) => (
  <Icon {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" opacity="0.001" /><path d="M19.4 13a7.8 7.8 0 0 0 0-2l2-1.5-2-3.4-2.4 1a7.8 7.8 0 0 0-1.7-1l-.3-2.6h-4l-.3 2.6a7.8 7.8 0 0 0-1.7 1l-2.4-1-2 3.4L4.6 11a7.8 7.8 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7.8 7.8 0 0 0 1.7 1l.3 2.6h4l.3-2.6a7.8 7.8 0 0 0 1.7-1l2.4 1 2-3.4z" /></Icon>
);
export const IconCheck = (p: P) => (<Icon {...p}><path d="M4 12l5 5L20 6" /></Icon>);
export const IconCopy = (p: P) => (
  <Icon {...p}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></Icon>
);
export const IconChevron = (p: P) => (<Icon {...p}><path d="M6 9l6 6 6-6" /></Icon>);
export const IconPlus = (p: P) => (<Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>);
export const IconSearch = (p: P) => (<Icon {...p}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></Icon>);
export const IconExternal = (p: P) => (
  <Icon {...p}><path d="M14 4h6v6" /><path d="M20 4l-9 9" /><path d="M19 14v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></Icon>
);
