"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { cn } from "@/lib/cn";
import { IconChevron } from "@/components/ui/icons";

interface ProjectLite {
  id: string;
  name: string;
  workspace: string;
}

function useDropdown() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);
  return { open, setOpen, ref };
}

function Switcher({
  orgSlug,
  projects,
  activeProjectId,
}: {
  orgSlug: string;
  projects: ProjectLite[];
  activeProjectId: string | null;
}) {
  const router = useRouter();
  const { open, setOpen, ref } = useDropdown();
  const active = projects.find((p) => p.id === activeProjectId) ?? projects[0];

  async function choose(id: string) {
    setOpen(false);
    await fetch("/api/project", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_id: id }),
    });
    router.refresh();
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-line/50"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded bg-graphite text-2xs font-semibold uppercase text-paper">
          {orgSlug.slice(0, 2)}
        </span>
        <span className="flex flex-col items-start leading-tight">
          <span className="text-2xs text-faint">{orgSlug}</span>
          <span className="max-w-[12rem] truncate text-[13px] font-medium text-ink">
            {active ? active.name : "No project"}
          </span>
        </span>
        <IconChevron className="text-faint" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 mt-1.5 w-72 animate-fade-in rounded-lg border border-line bg-surface p-1.5 shadow-pop">
          <p className="px-2 py-1 text-2xs font-semibold uppercase tracking-wider text-faint">
            Projects
          </p>
          {projects.length === 0 && (
            <p className="px-2 py-2 text-[13px] text-muted">
              No projects yet. Create one to start verifying.
            </p>
          )}
          <ul className="max-h-72 overflow-y-auto">
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => choose(p.id)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-line/50",
                    p.id === active?.id ? "text-ink" : "text-muted",
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-ink">{p.name}</span>
                    <span className="block truncate text-2xs text-faint">{p.workspace}</span>
                  </span>
                  {p.id === active?.id && <span className="h-1.5 w-1.5 rounded-full bg-assay" />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function UserMenu({ email }: { email: string }) {
  const router = useRouter();
  const { open, setOpen, ref } = useDropdown();

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  const initials = email.slice(0, 2).toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 w-8 items-center justify-center rounded-full border border-line-strong bg-paper text-2xs font-semibold text-ink hover:border-faint"
        aria-label="Account menu"
      >
        {initials}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-56 animate-fade-in rounded-lg border border-line bg-surface p-1.5 shadow-pop">
          <div className="border-b border-line px-2 pb-2 pt-1">
            <p className="truncate text-[13px] font-medium text-ink">{email}</p>
            <p className="text-2xs text-faint">Signed in</p>
          </div>
          <button
            onClick={logout}
            className="mt-1 w-full rounded-md px-2 py-1.5 text-left text-[13px] text-muted hover:bg-line/50 hover:text-ink"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Topbar({
  orgSlug,
  email,
  projects,
  activeProjectId,
}: {
  orgSlug: string;
  email: string;
  projects: ProjectLite[];
  activeProjectId: string | null;
}) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-line bg-paper/80 px-4 backdrop-blur">
      <Switcher orgSlug={orgSlug} projects={projects} activeProjectId={activeProjectId} />
      <UserMenu email={email} />
    </header>
  );
}
