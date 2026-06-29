import { NextRequest } from "next/server";

import { proxyTo } from "@/lib/api/server";

export const dynamic = "force-dynamic";

function target(req: NextRequest, path: string[]): string {
  return "/" + path.join("/") + (req.nextUrl.search || "");
}

export async function GET(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxyTo("cp", target(req, ctx.params.path), req);
}
export async function POST(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxyTo("cp", target(req, ctx.params.path), req);
}
export async function DELETE(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxyTo("cp", target(req, ctx.params.path), req);
}
