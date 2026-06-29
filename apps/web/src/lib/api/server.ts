import "server-only";

import { errorFromResponse } from "./errors";
import { getToken } from "../session";

/**
 * Server-side API access.
 *
 * `cp`/`rhd` are typed fetch helpers used by Server Components: they read the
 * session token from the httpOnly cookie and call the backend directly (no
 * self-proxy hop). `proxyTo` is the shared engine behind the BFF route handlers
 * that forward client-component requests with the same credentials.
 */

export const CONTROL_PLANE_URL =
  process.env.CONTROL_PLANE_URL || "http://localhost:8000";
export const RHD_URL = process.env.RHD_URL || "http://localhost:8030";
export const IVP_URL = process.env.IVP_URL || "http://localhost:8050";

type Backend = "cp" | "rhd" | "ivp";

function baseFor(backend: Backend): string {
  if (backend === "cp") return CONTROL_PLANE_URL;
  if (backend === "rhd") return RHD_URL;
  return IVP_URL;
}

interface FetchOpts {
  method?: string;
  body?: unknown;
  // Cache is off by default — dashboard data is live.
  revalidate?: number;
  query?: Record<string, string | number | boolean | undefined>;
}

function withQuery(path: string, query?: FetchOpts["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function call<T>(backend: Backend, path: string, opts: FetchOpts = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const res = await fetch(baseFor(backend) + withQuery(path, opts.query), {
    method: opts.method || "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    cache: opts.revalidate ? "force-cache" : "no-store",
    next: opts.revalidate ? { revalidate: opts.revalidate } : undefined,
  });
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const cp = {
  get: <T>(path: string, query?: FetchOpts["query"]) => call<T>("cp", path, { query }),
  post: <T>(path: string, body?: unknown) => call<T>("cp", path, { method: "POST", body }),
  del: <T>(path: string) => call<T>("cp", path, { method: "DELETE" }),
};

export const rhd = {
  get: <T>(path: string, query?: FetchOpts["query"]) => call<T>("rhd", path, { query }),
  post: <T>(path: string, body?: unknown) => call<T>("rhd", path, { method: "POST", body }),
};

export const ivp = {
  get: <T>(path: string, query?: FetchOpts["query"]) => call<T>("ivp", path, { query }),
  post: <T>(path: string, body?: unknown) => call<T>("ivp", path, { method: "POST", body }),
};

/** Forward a client request to a backend, attaching the session token. */
export async function proxyTo(backend: Backend, path: string, req: Request): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `Bearer ${token}`;
  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  const upstream = await fetch(baseFor(backend) + path, init);
  const body = await upstream.text();
  return new Response(body || null, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") || "application/json",
    },
  });
}
