import { NextResponse } from "next/server";

// Liveness endpoint for the dashboard BFF. Used by the docker-compose
// healthcheck and the `make health` command. Never touches upstreams, so a
// failing control-plane/RHD does not mark the dashboard itself unhealthy.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "web" });
}
