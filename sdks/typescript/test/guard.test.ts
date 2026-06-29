import { describe, expect, it } from "vitest";

import { Blocked, InlineGuard, type InlineDecision } from "../src/guard.js";
import type { FetchLike } from "../src/http.js";

interface Recorded {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function mockFetch(
  handler: (rec: Recorded) => { status?: number; body?: unknown },
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
    return new Response(res.body === undefined ? "" : JSON.stringify(res.body), { status });
  };
  return { fetch, calls };
}

function decision(action: string, extra: Partial<InlineDecision> = {}): InlineDecision {
  return {
    decision_id: "d1",
    action: action as InlineDecision["action"],
    risk_score: 0.1,
    risk_band: "low",
    reasons: {},
    latency_ms: 1,
    content_sha256: "abc",
    mode: "enforce",
    redacted_content: null,
    escalation: null,
    degraded: false,
    ...extra,
  };
}

describe("InlineGuard.enforce", () => {
  it("returns the content on allow", async () => {
    const { fetch } = mockFetch(() => ({ body: decision("allow") }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    expect(await guard.enforce("hello", { policySlug: "p" })).toBe("hello");
  });

  it("returns redacted content on redact", async () => {
    const { fetch } = mockFetch(() => ({
      body: decision("redact", { redacted_content: "he[REDACTED]", risk_score: 0.6 }),
    }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    expect(await guard.enforce("hello", { policySlug: "p" })).toBe("he[REDACTED]");
  });

  it("throws Blocked on block", async () => {
    const { fetch } = mockFetch(() => ({ body: decision("block", { risk_score: 0.95 }) }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    await expect(guard.enforce("hello", { policySlug: "p" })).rejects.toBeInstanceOf(Blocked);
  });

  it("invokes onEscalate and passes content through", async () => {
    const { fetch } = mockFetch(() => ({ body: decision("escalate") }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    let seen: InlineDecision | undefined;
    const out = await guard.enforce("hello", { policySlug: "p", onEscalate: (d) => (seen = d) });
    expect(out).toBe("hello");
    expect(seen?.action).toBe("escalate");
  });

  it("sends auth and mapped body", async () => {
    const { fetch, calls } = mockFetch(() => ({ body: decision("allow") }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    await guard.check("payload", { policySlug: "prod", latencyBudgetMs: 50 });
    const first = calls[0]!;
    expect(first.headers["authorization"]).toBe("Bearer tsk_a_b");
    expect((first.body as Record<string, unknown>).content).toBe("payload");
    expect((first.body as Record<string, unknown>).policy_slug).toBe("prod");
    expect((first.body as Record<string, unknown>).latency_budget_ms).toBe(50);
  });
});

describe("InlineGuard.stream", () => {
  it("returns verdicts with a terminal block", async () => {
    const { fetch } = mockFetch(() => ({
      body: [
        { seq: 0, action: "allow", terminal: false, decision: decision("allow") },
        { seq: 1, action: "block", terminal: true, decision: decision("block") },
      ],
    }));
    const guard = new InlineGuard({ baseUrl: "http://ivp", apiKey: "tsk_a_b", fetch });
    const verdicts = await guard.stream(["a", "b"], { policySlug: "p" });
    expect(verdicts.at(-1)?.terminal).toBe(true);
    expect(verdicts.at(-1)?.action).toBe("block");
  });
});
