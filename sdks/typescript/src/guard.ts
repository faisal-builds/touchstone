/**
 * Inline guard — client middleware for the Touchstone Inline Verification Plane.
 *
 * Wrap a model/agent output and enforce the plane's verdict:
 *
 * ```ts
 * const guard = new InlineGuard({ baseUrl: "http://localhost:8050", apiKey: "tsk_..." });
 * const safe = await guard.enforce(modelOutput, { policySlug: "prod" }); // text, or throws Blocked
 * ```
 *
 * Semantics: allow → original content; redact → redacted content; escalate →
 * original content (deep verdict resolves async); block → throws {@link Blocked}.
 * {@link InlineGuard.stream} feeds chunks and stops early when the plane blocks.
 */

import { TouchstoneError } from "./errors.js";
import { HttpClient, type FetchLike } from "./http.js";

export type InlineAction = "allow" | "block" | "redact" | "escalate";

export interface InlineDecision {
  decision_id: string;
  action: InlineAction;
  risk_score: number;
  risk_band: string;
  reasons: Record<string, unknown>;
  latency_ms: number;
  content_sha256: string;
  mode: string;
  redacted_content: string | null;
  escalation: Record<string, unknown> | null;
  degraded: boolean;
}

export interface StreamVerdict {
  seq: number;
  action: InlineAction;
  terminal: boolean;
  decision: InlineDecision;
}

/** Thrown by {@link InlineGuard.enforce} when the plane blocks the content. */
export class Blocked extends TouchstoneError {
  readonly decision: InlineDecision;
  constructor(decision: InlineDecision) {
    super(`inline plane blocked content (risk=${decision.risk_score})`, { status: 200 });
    this.name = "Blocked";
    this.decision = decision;
  }
}

export interface InlineGuardOptions {
  baseUrl?: string;
  apiKey?: string;
  token?: string;
  fetch?: FetchLike;
  timeoutMs?: number;
}

export interface CheckOptions {
  policySlug?: string;
  policyId?: string;
  latencyBudgetMs?: number;
  mode?: "enforce" | "shadow";
  context?: Record<string, unknown>;
}

export interface EnforceOptions extends CheckOptions {
  onEscalate?: (decision: InlineDecision) => void;
}

export class InlineGuard {
  private apiKey: string | undefined;
  private token: string | undefined;
  private readonly http: HttpClient;

  constructor(options: InlineGuardOptions = {}) {
    this.apiKey = options.apiKey;
    this.token = options.token;
    const baseUrl = options.baseUrl ?? "http://localhost:8050";
    this.http = new HttpClient(baseUrl, {
      getAuthHeader: (): Record<string, string> => {
        const cred = this.apiKey ?? this.token;
        return cred ? { Authorization: `Bearer ${cred}` } : {};
      },
      ...(options.fetch ? { fetchImpl: options.fetch } : {}),
      ...(options.timeoutMs ? { timeoutMs: options.timeoutMs } : {}),
    });
  }

  setApiKey(apiKey: string): void {
    this.apiKey = apiKey;
  }

  /** Call the plane and return the raw decision (no enforcement). */
  async check(content: string, options: CheckOptions = {}): Promise<InlineDecision> {
    return this.http.request<InlineDecision>("/v1/inline/verify", {
      method: "POST",
      body: {
        content,
        policy_slug: options.policySlug ?? null,
        policy_id: options.policyId ?? null,
        latency_budget_ms: options.latencyBudgetMs ?? null,
        mode: options.mode ?? "enforce",
        context: options.context ?? {},
      },
    });
  }

  /** Enforce the verdict: resolve with safe text, or throw {@link Blocked}. */
  async enforce(content: string, options: EnforceOptions = {}): Promise<string> {
    const decision = await this.check(content, options);
    if (decision.action === "block") throw new Blocked(decision);
    if (decision.action === "redact") return decision.redacted_content ?? "";
    if (decision.action === "escalate" && options.onEscalate) options.onEscalate(decision);
    return content;
  }

  /** Stream-verify chunks; the plane early-exits on a terminal verdict. */
  async stream(chunks: string[], options: CheckOptions = {}): Promise<StreamVerdict[]> {
    return this.http.request<StreamVerdict[]>("/v1/inline/verify/stream", {
      method: "POST",
      body: {
        chunks,
        policy_slug: options.policySlug ?? null,
        policy_id: options.policyId ?? null,
        latency_budget_ms: options.latencyBudgetMs ?? null,
        mode: options.mode ?? "enforce",
      },
    });
  }
}
