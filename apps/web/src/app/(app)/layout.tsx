import { redirect } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { resolveContext } from "@/lib/context";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const ctx = await resolveContext();
  if (!ctx) redirect("/login");

  return (
    <div className="flex min-h-screen bg-paper">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>
      <div className="flex min-h-screen flex-1 flex-col lg:pl-60">
        <Topbar
          orgSlug={ctx.session.orgSlug}
          email={ctx.session.email}
          projects={ctx.projects}
          activeProjectId={ctx.activeProjectId}
        />
        <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-7 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
