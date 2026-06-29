import { NextRequest, NextResponse } from "next/server";

import { errorFromResponse } from "@/lib/api/errors";
import { CONTROL_PLANE_URL } from "@/lib/api/server";
import type { TokenPair } from "@/lib/api/types";
import { setSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { email, password, org_name, org_slug, full_name } = await req.json();
  const res = await fetch(`${CONTROL_PLANE_URL}/v1/auth/signup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password, org_name, org_slug, full_name: full_name || null }),
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await errorFromResponse(res);
    return NextResponse.json({ title: err.title, detail: err.detail }, { status: err.status });
  }
  const pair = (await res.json()) as TokenPair;
  setSession(
    { token: pair.access_token, orgId: pair.org_id, orgSlug: pair.org_slug, email },
    pair.expires_in,
  );
  return NextResponse.json({ org_slug: pair.org_slug });
}
