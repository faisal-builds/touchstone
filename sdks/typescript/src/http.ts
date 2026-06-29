/**
 * Low-level HTTP transport.
 *
 * A thin wrapper over the global `fetch` (Node >=18 and all modern browsers) so
 * the SDK ships with zero runtime dependencies. Handles auth headers, query
 * strings, JSON encode/decode, per-request timeouts, and turning error
 * responses into typed {@link TouchstoneError}s. A custom `fetch` may be
 * injected for testing or non-standard runtimes.
 */

import { errorForStatus, type ProblemJson } from "./errors.js";
import { VERSION } from "./version.js";

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export type QueryValue = string | number | boolean | undefined | null;

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

export interface HttpClientOptions {
  getAuthHeader: () => Record<string, string>;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
}

function buildUrl(baseUrl: string, path: string, query?: RequestOptions["query"]): string {
  let url = baseUrl + path;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    }
    const qs = params.toString();
    if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  }
  return url;
}

export class HttpClient {
  private readonly baseUrl: string;
  private readonly getAuthHeader: () => Record<string, string>;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;

  constructor(baseUrl: string, options: HttpClientOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.getAuthHeader = options.getAuthHeader;
    const f = options.fetchImpl ?? globalThis.fetch;
    if (typeof f !== "function") {
      throw new Error(
        "global fetch is unavailable; pass `fetch` in the client options (Node >=18 required)",
      );
    }
    // Bind to globalThis so the native implementation keeps its receiver.
    this.fetchImpl = options.fetchImpl ?? ((input, init) => globalThis.fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? 30_000;
  }

  async request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const url = buildUrl(this.baseUrl, path, opts.query);
    const headers: Record<string, string> = {
      accept: "application/json",
      "user-agent": `touchstone-typescript/${VERSION}`,
      ...this.getAuthHeader(),
    };
    if (opts.body !== undefined) headers["content-type"] = "application/json";

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const onAbort = () => controller.abort();
    if (opts.signal) {
      if (opts.signal.aborted) controller.abort();
      else opts.signal.addEventListener("abort", onAbort, { once: true });
    }

    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method: opts.method ?? "GET",
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
      if (opts.signal) opts.signal.removeEventListener("abort", onAbort);
    }

    if (!res.ok) {
      let body: ProblemJson = {};
      try {
        body = (await res.json()) as ProblemJson;
      } catch {
        body = { detail: await res.text().catch(() => "") };
      }
      const retryAfterRaw = res.headers.get("retry-after");
      const retryAfter = retryAfterRaw ? Number.parseInt(retryAfterRaw, 10) : undefined;
      throw errorForStatus(res.status, body, Number.isNaN(retryAfter) ? undefined : retryAfter);
    }

    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }
}
