import "server-only";

import { cp } from "./api/server";
import { getActiveProject, getSession } from "./session";
import type { Project, SessionInfo, Workspace } from "./api/types";

export interface ProjectLite {
  id: string;
  name: string;
  slug: string;
  workspaceId: string;
  workspace: string;
}

export interface AppContext {
  session: SessionInfo;
  projects: ProjectLite[];
  activeProjectId: string | null;
  /** True when the backend could not be reached. */
  degraded: boolean;
}

/** Load the projects across the org's workspaces, flattened for the switcher. */
export async function loadProjects(): Promise<{ projects: ProjectLite[]; degraded: boolean }> {
  try {
    const workspaces = await cp.get<Workspace[]>("/v1/workspaces");
    const byId = new Map(workspaces.map((w) => [w.id, w.name]));
    const lists = await Promise.all(
      workspaces.map((w) =>
        cp.get<Project[]>(`/v1/workspaces/${w.id}/projects`).catch(() => [] as Project[]),
      ),
    );
    const projects = lists.flat().map((p) => ({
      id: p.id,
      name: p.name,
      slug: p.slug,
      workspaceId: p.workspace_id,
      workspace: byId.get(p.workspace_id) ?? "Workspace",
    }));
    return { projects, degraded: false };
  } catch {
    return { projects: [], degraded: true };
  }
}

export async function resolveContext(): Promise<AppContext | null> {
  const session = getSession();
  if (!session) return null;
  const { projects, degraded } = await loadProjects();
  const cookieProject = getActiveProject();
  const activeProjectId =
    (cookieProject && projects.some((p) => p.id === cookieProject) ? cookieProject : null) ??
    projects[0]?.id ??
    null;
  return { session, projects, activeProjectId, degraded };
}
