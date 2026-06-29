import { NextResponse } from "next/server";

import { clearSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST() {
  clearSession();
  return NextResponse.json({ ok: true });
}
