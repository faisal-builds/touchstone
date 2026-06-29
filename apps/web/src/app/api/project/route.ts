import { NextRequest, NextResponse } from "next/server";

import { setActiveProject } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { project_id } = await req.json();
  if (typeof project_id !== "string" || !project_id) {
    return NextResponse.json({ title: "project_id is required" }, { status: 400 });
  }
  setActiveProject(project_id);
  return NextResponse.json({ ok: true });
}
