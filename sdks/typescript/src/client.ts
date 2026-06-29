/**
 * The Touchstone API client.
 *
 * One client speaks to both backend services — the control-plane (auth, tenancy,
 * verifier registry, verifications, audit) and the reward-hacking-detector
 * (robustness evaluations and the exploit corpus). Both accept the same
 * credential (an API key or a user JWT), sent as `Authorization: Bearer`.
 *
 * @example
 * ```ts
 * import { TouchstoneClient } from "@touchstone/sdk";
 *
 * const client = new TouchstoneClient({ baseUrl: "http://localhost:8000" });
 * await client.signup({ email: "me@acme.com", password: "...", orgName: "Acme", orgSlug: "acme" });
 * const key = await client.createApiKey("ci", { role: "member" });
 * client.setApiKey(key.secret);
 * const ws = await client.createWorkspace("Research", "research");
 * const project = await client.createProject(ws.id, "Coding Agent", "coding-agent");
 * const verifier = await client.registerVerifier(project.id, "Answer 42", "answer-42", "code", {
 *   code: "def check(a):\n return {'score': 1.0 if a.get('answer')==42 else 0.0}",
 *   threshold: 1.0,
 * });
 * const run = await client.submitVerification(verifier.id, "demo/run.json");
 * const result = await client.waitForVerification(run.id);
 * console.log(result.status, result.score, result.passed);
 * ```
 */

import { PollTimeoutError } from "./errors.js";
import { HttpClient, type FetchLike } from "./http.js";
import {
  isTerminal,
  type ApiKey,
  type ApiKeyCreated,
  type AuditRecord,
  type Comparison,
  type CreateApiKeyOptions,
  type CreateProjectOptions,
  type Evaluation,
  type EvaluationReport,
  type Exploit,
  type LaunchEvaluationOptions,
  type ListVerificationsOptions,
  type LoginRequest,
  type Project,
  type SearchExploitsOptions,
  type SignupRequest,
  type TokenPair,
  type Trend,
  type Verification,
  type Verifier,
  type VerifierType,
  type WaitOptions,
  type Workspace,
} from "./types.js";

export interface TouchstoneClientOptions {
  /** Control-plane base URL. Default `http://localhost:8000`. */
  baseUrl?: string;
  /** Reward-hacking-detector base URL. Defaults to `baseUrl`. */
  rhdUrl?: string;
  /** API key credential (`tsk_…`). Takes precedence over `token`. */
  apiKey?: string;
  /** User JWT credential (from `signup`/`login`). */
  token?: string;
  /** Per-request timeout in milliseconds. Default 30000. */
  timeoutMs?: number;
  /** Custom fetch implementation (for testing or non-standard runtimes). */
  fetch?: FetchLike;
}

const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error("aborted"));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new Error("aborted"));
      },
      { once: true },
    );
  });

export class TouchstoneClient {
  private apiKey: string | undefined;
  private token: string | undefined;
  private readonly cp: HttpClient;
  private readonly rhd: HttpClient;

  constructor(options: TouchstoneClientOptions = {}) {
    this.apiKey = options.apiKey;
    this.token = options.token;
    const baseUrl = options.baseUrl ?? "http://localhost:8000";
    const rhdUrl = options.rhdUrl ?? baseUrl;
    const shared = {
      getAuthHeader: () => this.authHeader(),
      timeoutMs: options.timeoutMs,
      ...(options.fetch ? { fetchImpl: options.fetch } : {}),
    };
    this.cp = new HttpClient(baseUrl, shared);
    this.rhd = new HttpClient(rhdUrl, shared);
  }

  // --- credentials ----------------------------------------------------------

  setApiKey(apiKey: string): void {
    this.apiKey = apiKey;
  }

  setToken(token: string): void {
    this.token = token;
  }

  /** The currently active bearer credential (API key wins over token), if any. */
  get credential(): string | undefined {
    return this.apiKey ?? this.token;
  }

  private authHeader(): Record<string, string> {
    const cred = this.apiKey ?? this.token;
    return cred ? { authorization: `Bearer ${cred}` } : {};
  }

  // --- auth -----------------------------------------------------------------

  /** Create an organization + owner user and store the returned JWT. */
  async signup(req: SignupRequest): Promise<TokenPair> {
    const pair = await this.cp.request<TokenPair>("/v1/auth/signup", {
      method: "POST",
      body: {
        email: req.email,
        password: req.password,
        org_name: req.orgName,
        org_slug: req.orgSlug,
        full_name: req.fullName ?? null,
      },
    });
    this.token = pair.access_token;
    return pair;
  }

  /** Authenticate an existing user and store the returned JWT. */
  async login(req: LoginRequest): Promise<TokenPair> {
    const pair = await this.cp.request<TokenPair>("/v1/auth/login", {
      method: "POST",
      body: { email: req.email, password: req.password, org_slug: req.orgSlug ?? null },
    });
    this.token = pair.access_token;
    return pair;
  }

  // --- api keys -------------------------------------------------------------

  /** Create an API key. The plaintext `secret` is returned exactly once. */
  async createApiKey(name: string, options: CreateApiKeyOptions = {}): Promise<ApiKeyCreated> {
    return this.cp.request<ApiKeyCreated>("/v1/api-keys", {
      method: "POST",
      body: {
        name,
        role: options.role ?? "service",
        project_id: options.projectId ?? null,
      },
    });
  }

  listApiKeys(): Promise<ApiKey[]> {
    return this.cp.request<ApiKey[]>("/v1/api-keys");
  }

  revokeApiKey(keyId: string): Promise<void> {
    return this.cp.request<void>(`/v1/api-keys/${encodeURIComponent(keyId)}`, {
      method: "DELETE",
    });
  }

  // --- workspaces / projects ------------------------------------------------

  createWorkspace(name: string, slug: string): Promise<Workspace> {
    return this.cp.request<Workspace>("/v1/workspaces", {
      method: "POST",
      body: { name, slug },
    });
  }

  listWorkspaces(): Promise<Workspace[]> {
    return this.cp.request<Workspace[]>("/v1/workspaces");
  }

  getWorkspace(workspaceId: string): Promise<Workspace> {
    return this.cp.request<Workspace>(`/v1/workspaces/${encodeURIComponent(workspaceId)}`);
  }

  createProject(
    workspaceId: string,
    name: string,
    slug: string,
    options: CreateProjectOptions = {},
  ): Promise<Project> {
    return this.cp.request<Project>(
      `/v1/workspaces/${encodeURIComponent(workspaceId)}/projects`,
      { method: "POST", body: { name, slug, description: options.description ?? null } },
    );
  }

  listProjects(workspaceId: string): Promise<Project[]> {
    return this.cp.request<Project[]>(
      `/v1/workspaces/${encodeURIComponent(workspaceId)}/projects`,
    );
  }

  // --- verifiers ------------------------------------------------------------

  registerVerifier(
    projectId: string,
    name: string,
    slug: string,
    verifierType: VerifierType,
    definition: Record<string, unknown>,
  ): Promise<Verifier> {
    return this.cp.request<Verifier>(
      `/v1/projects/${encodeURIComponent(projectId)}/verifiers`,
      {
        method: "POST",
        body: { name, slug, verifier_type: verifierType, definition },
      },
    );
  }

  listVerifiers(projectId: string): Promise<Verifier[]> {
    return this.cp.request<Verifier[]>(
      `/v1/projects/${encodeURIComponent(projectId)}/verifiers`,
    );
  }

  getVerifier(projectId: string, verifierId: string): Promise<Verifier> {
    return this.cp.request<Verifier>(
      `/v1/projects/${encodeURIComponent(projectId)}/verifiers/${encodeURIComponent(verifierId)}`,
    );
  }

  deleteVerifier(projectId: string, verifierId: string): Promise<void> {
    return this.cp.request<void>(
      `/v1/projects/${encodeURIComponent(projectId)}/verifiers/${encodeURIComponent(verifierId)}`,
      { method: "DELETE" },
    );
  }

  // --- verifications --------------------------------------------------------

  submitVerification(
    verifierId: string,
    artifactRef: string,
    options: { idempotencyKey?: string } = {},
  ): Promise<Verification> {
    return this.cp.request<Verification>("/v1/verifications", {
      method: "POST",
      body: {
        verifier_id: verifierId,
        artifact_ref: artifactRef,
        idempotency_key: options.idempotencyKey ?? null,
      },
    });
  }

  getVerification(verificationId: string): Promise<Verification> {
    return this.cp.request<Verification>(
      `/v1/verifications/${encodeURIComponent(verificationId)}`,
    );
  }

  listVerifications(options: ListVerificationsOptions = {}): Promise<Verification[]> {
    return this.cp.request<Verification[]>("/v1/verifications", {
      query: {
        project_id: options.projectId,
        verifier_id: options.verifierId,
        limit: options.limit,
      },
    });
  }

  /** Poll a verification until it reaches a terminal state or the deadline passes. */
  async waitForVerification(
    verificationId: string,
    options: WaitOptions = {},
  ): Promise<Verification> {
    const timeoutMs = options.timeoutMs ?? 60_000;
    const intervalMs = options.intervalMs ?? 500;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const run = await this.getVerification(verificationId);
      if (isTerminal(run.status)) return run;
      if (Date.now() >= deadline) {
        throw new PollTimeoutError(
          `verification ${verificationId} still ${run.status} after ${timeoutMs}ms`,
        );
      }
      await sleep(intervalMs, options.signal);
    }
  }

  // --- audit ----------------------------------------------------------------

  listAudit(options: { limit?: number } = {}): Promise<AuditRecord[]> {
    return this.cp.request<AuditRecord[]>("/v1/audit", {
      query: { limit: options.limit },
    });
  }

  // --- robustness (reward-hacking-detector) ---------------------------------

  launchEvaluation(verifierId: string, options: LaunchEvaluationOptions = {}): Promise<Evaluation> {
    return this.rhd.request<Evaluation>("/v1/robustness/evaluations", {
      method: "POST",
      body: {
        verifier_id: verifierId,
        seed_cases: options.seedCases ?? [],
        seed: options.seed ?? null,
        max_attacks: options.maxAttacks ?? null,
        enable_model_attacks: options.enableModelAttacks ?? false,
      },
    });
  }

  getEvaluation(evaluationId: string): Promise<Evaluation> {
    return this.rhd.request<Evaluation>(
      `/v1/robustness/evaluations/${encodeURIComponent(evaluationId)}`,
    );
  }

  getEvaluationReport(evaluationId: string): Promise<EvaluationReport> {
    return this.rhd.request<EvaluationReport>(
      `/v1/robustness/evaluations/${encodeURIComponent(evaluationId)}/report`,
    );
  }

  listVerifierEvaluations(verifierId: string): Promise<Evaluation[]> {
    return this.rhd.request<Evaluation[]>(
      `/v1/robustness/verifiers/${encodeURIComponent(verifierId)}/evaluations`,
    );
  }

  listVerifierExploits(verifierId: string): Promise<Exploit[]> {
    return this.rhd.request<Exploit[]>(
      `/v1/robustness/verifiers/${encodeURIComponent(verifierId)}/exploits`,
    );
  }

  getVerifierTrend(verifierId: string): Promise<Trend> {
    return this.rhd.request<Trend>(
      `/v1/robustness/verifiers/${encodeURIComponent(verifierId)}/trend`,
    );
  }

  compareEvaluations(
    baselineEvaluationId: string,
    candidateEvaluationId: string,
  ): Promise<Comparison> {
    return this.rhd.request<Comparison>("/v1/robustness/compare", {
      method: "POST",
      body: {
        baseline_evaluation_id: baselineEvaluationId,
        candidate_evaluation_id: candidateEvaluationId,
      },
    });
  }

  searchExploits(options: SearchExploitsOptions = {}): Promise<Exploit[]> {
    return this.rhd.request<Exploit[]>("/v1/robustness/exploits/search", {
      query: {
        verifier_id: options.verifierId,
        verifier_version: options.verifierVersion,
        category: options.category,
        severity: options.severity,
        strategy: options.strategy,
        min_score: options.minScore,
        q: options.q,
        limit: options.limit,
        offset: options.offset,
      },
    });
  }

  /** Poll a robustness evaluation until terminal or the deadline passes. */
  async waitForEvaluation(evaluationId: string, options: WaitOptions = {}): Promise<Evaluation> {
    const timeoutMs = options.timeoutMs ?? 120_000;
    const intervalMs = options.intervalMs ?? 1_000;
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const evaluation = await this.getEvaluation(evaluationId);
      if (isTerminal(evaluation.status)) return evaluation;
      if (Date.now() >= deadline) {
        throw new PollTimeoutError(
          `evaluation ${evaluationId} still ${evaluation.status} after ${timeoutMs}ms`,
        );
      }
      await sleep(intervalMs, options.signal);
    }
  }

  // --- health ---------------------------------------------------------------

  health(): Promise<{ status: string }> {
    return this.cp.request<{ status: string }>("/healthz");
  }

  ready(): Promise<{ status: string; checks?: Record<string, string> }> {
    return this.cp.request("/readyz");
  }
}
