import { describe, expect, it, vi } from "vitest";

import { TouchstoneClient } from "../src/client.js";
import { ConflictError, NotFoundError, PollTimeoutError, RateLimitError } from "../src/errors.js";
import type { FetchLike } from "../src/http.js";

interface Recorded {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

/** Build a mock fetch that records requests and replays scripted responses. */
function mockFetch(
  handler: (rec: Recorded) => { status?: number; body?: unknown; headers?: Record<string, string> },
): { fetch: FetchLike; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const fetch: FetchLike = async (url, init) => {
    const headers: Record<string, string> = {};
    const h = init?.headers as Record<string, string> | undefined;
    if (h) for (const [k, v] of Object.entries(h)) headers[k.toLowerCase()] = v;
    const rec: Recorded = {
      url,
      method: init?.method ?? "GET",
      headers,
      body: init?.body ? JSON.parse(init.body as string) : undefined,
    };
    calls.push(rec);
    const res = handler(rec);
    const status = res.status ?? 200;
    const nullBody = status === 204 || status === 205 || status === 304;
    const payload = nullBody ? null : res.body === undefined ? "" : JSON.stringify(res.body);
    return new Response(payload, { status, headers: res.headers });
  };
  return { fetch, calls };
}

const TOKEN = { access_token: "jwt-abc", token_type: "Bearer", expires_in: 3600, org_id: "o1", org_slug: "acme" };

describe("auth", () => {
  it("signup posts mapped body and stores the token", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: TOKEN }));
    const client = new TouchstoneClient({ fetch });
    const pair = await client.signup({
      email: "me@acme.com", password: "pw", orgName: "Acme", orgSlug: "acme", fullName: "Me",
    });
    expect(pair.access_token).toBe("jwt-abc");
    expect(client.credential).toBe("jwt-abc");
    const call = calls[0]!;
    expect(call.url).toBe("http://localhost:8000/v1/auth/signup");
    expect(call.method).toBe("POST");
    expect(call.body).toEqual({
      email: "me@acme.com", password: "pw", org_name: "Acme", org_slug: "acme", full_name: "Me",
    });
  });

  it("login stores the token and defaults org_slug to null", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: TOKEN }));
    const client = new TouchstoneClient({ fetch });
    await client.login({ email: "me@acme.com", password: "pw" });
    expect(calls[0]!.body).toEqual({ email: "me@acme.com", password: "pw", org_slug: null });
    expect(client.credential).toBe("jwt-abc");
  });
});

describe("credentials", () => {
  it("sends the bearer header and prefers the API key over the token", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: [] }));
    const client = new TouchstoneClient({ fetch, token: "the-jwt" });
    await client.listApiKeys();
    expect(calls[0]!.headers["authorization"]).toBe("Bearer the-jwt");

    client.setApiKey("tsk_123");
    await client.listApiKeys();
    expect(calls[1]!.headers["authorization"]).toBe("Bearer tsk_123");
  });

  it("omits the auth header when no credential is set", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: { status: "ok" } }));
    const client = new TouchstoneClient({ fetch });
    await client.health();
    expect(calls[0]!.headers["authorization"]).toBeUndefined();
  });
});

describe("resources", () => {
  it("createApiKey defaults role to service and returns the secret", async () => {
    const created = { id: "k1", name: "ci", key_id: "kid", role: "service", project_id: null,
      last_used_at: null, expires_at: null, revoked_at: null, created_at: "t", secret: "tsk_secret" };
    const { fetch, calls } = mockFetch(() => ({ body: created }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    const key = await client.createApiKey("ci");
    expect(key.secret).toBe("tsk_secret");
    expect(calls[0]!.body).toEqual({ name: "ci", role: "service", project_id: null });
  });

  it("registerVerifier targets the nested project path", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: { id: "v1" } }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await client.registerVerifier("p1", "Answer", "answer", "code", { threshold: 1 });
    expect(calls[0]!.url).toBe("http://localhost:8000/v1/projects/p1/verifiers");
    expect(calls[0]!.body).toEqual({
      name: "Answer", slug: "answer", verifier_type: "code", definition: { threshold: 1 },
    });
  });

  it("listVerifications serializes query params and drops undefined", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: [] }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await client.listVerifications({ projectId: "p1", limit: 10 });
    expect(calls[0]!.url).toBe("http://localhost:8000/v1/verifications?project_id=p1&limit=10");
  });

  it("revokeApiKey issues a DELETE", async () => {
    const { fetch, calls } = mockFetch(() => ({ status: 204 }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await client.revokeApiKey("kid");
    expect(calls[0]!.method).toBe("DELETE");
    expect(calls[0]!.url).toBe("http://localhost:8000/v1/api-keys/kid");
  });
});

describe("robustness routes to the RHD base url", () => {
  it("uses rhdUrl for evaluations and exploit search", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: [] }));
    const client = new TouchstoneClient({
      fetch, token: "t", baseUrl: "http://cp:8000", rhdUrl: "http://rhd:8030",
    });
    await client.searchExploits({ verifierId: "v1", severity: "high", q: "inject" });
    expect(calls[0]!.url).toBe(
      "http://rhd:8030/v1/robustness/exploits/search?verifier_id=v1&severity=high&q=inject",
    );
  });

  it("launchEvaluation posts mapped options", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: { id: "e1", status: "pending" } }));
    const client = new TouchstoneClient({ fetch, token: "t", rhdUrl: "http://rhd:8030" });
    await client.launchEvaluation("v1", { seed: 7, maxAttacks: 50, enableModelAttacks: true });
    expect(calls[0]!.url).toBe("http://rhd:8030/v1/robustness/evaluations");
    expect(calls[0]!.body).toEqual({
      verifier_id: "v1", seed_cases: [], seed: 7, max_attacks: 50, enable_model_attacks: true,
    });
  });
});

describe("error handling", () => {
  it("throws typed errors from problem+json", async () => {
    const { fetch } = mockFetch(() => ({ status: 404, body: { detail: "no such verifier" } }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await expect(client.getVerifier("p1", "v9")).rejects.toBeInstanceOf(NotFoundError);
  });

  it("maps 409 to ConflictError", async () => {
    const { fetch } = mockFetch(() => ({ status: 409, body: { detail: "slug taken" } }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await expect(client.createWorkspace("X", "x")).rejects.toBeInstanceOf(ConflictError);
  });

  it("parses Retry-After into RateLimitError", async () => {
    const { fetch } = mockFetch(() => ({
      status: 429, body: { detail: "slow down" }, headers: { "retry-after": "12" },
    }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await client.listApiKeys().then(
      () => { throw new Error("expected rejection"); },
      (err: unknown) => {
        expect(err).toBeInstanceOf(RateLimitError);
        expect((err as RateLimitError).retryAfter).toBe(12);
      },
    );
  });
});

describe("polling", () => {
  it("waitForVerification resolves once terminal", async () => {
    const statuses = ["pending", "running", "completed"];
    let i = 0;
    const { fetch } = mockFetch(() => ({ body: { id: "r1", status: statuses[i++] ?? "completed" } }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    const run = await client.waitForVerification("r1", { intervalMs: 1, timeoutMs: 1000 });
    expect(run.status).toBe("completed");
    expect(i).toBe(3);
  });

  it("waitForVerification throws PollTimeoutError past the deadline", async () => {
    const { fetch } = mockFetch(() => ({ body: { id: "r1", status: "running" } }));
    const client = new TouchstoneClient({ fetch, token: "t" });
    await expect(
      client.waitForVerification("r1", { intervalMs: 1, timeoutMs: 5 }),
    ).rejects.toBeInstanceOf(PollTimeoutError);
  });
});

describe("transport", () => {
  it("aborts on timeout via AbortController", async () => {
    const slowFetch: FetchLike = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      });
    const client = new TouchstoneClient({ fetch: slowFetch, token: "t", timeoutMs: 5 });
    await expect(client.health()).rejects.toThrow();
  });

  it("uses the injected fetch (not global) and returns parsed JSON", async () => {
    const spy = vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    const client = new TouchstoneClient({ fetch: spy as unknown as FetchLike, token: "t" });
    const out = await client.health();
    expect(out).toEqual({ status: "ok" });
    expect(spy).toHaveBeenCalledOnce();
  });
});
