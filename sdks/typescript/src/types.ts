/**
 * Typed request/response models for the Touchstone SDK.
 *
 * These mirror the control-plane and reward-hacking-detector response schemas
 * (OpenAPI 3.1) so callers get full types, autocompletion, and compile-time
 * safety instead of raw JSON. Timestamps are ISO-8601 strings, exactly as the
 * API returns them; UUIDs are typed as strings.
 */

// --- enums (as string-literal unions) ---------------------------------------

export type Role = "owner" | "admin" | "member" | "viewer" | "service";

export type VerifierType = "code" | "model" | "process" | "hybrid";

export type VerificationStatus = "pending" | "running" | "completed" | "failed";

export type EvaluationStatus = "pending" | "running" | "completed" | "failed";

export type Severity = "low" | "medium" | "high" | "critical";

export type ExploitCategory =
  | "content_corruption"
  | "judge_manipulation"
  | "length_bias"
  | "formatting_exploit"
  | "edge_case"
  | "model_generated";

export type TrendDirection =
  | "improving"
  | "declining"
  | "stable"
  | "insufficient_data";

/** Verification/evaluation statuses past which no further transition occurs. */
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  "completed",
  "failed",
]);

export function isTerminal(status: VerificationStatus | EvaluationStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

// --- control-plane models ---------------------------------------------------

export interface TokenPair {
  access_token: string;
  token_type: string;
  expires_in: number;
  org_id: string;
  org_slug: string;
}

export interface ApiKey {
  id: string;
  name: string;
  key_id: string;
  role: Role;
  project_id: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/** Returned only at creation — `secret` is the full plaintext key, shown once. */
export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface Workspace {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  created_at: string;
}

export interface Verifier {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  version: number;
  verifier_type: VerifierType;
  definition: Record<string, unknown>;
  robustness_score: number | null;
  is_active: boolean;
  created_at: string;
}

export interface Verification {
  id: string;
  project_id: string;
  verifier_id: string;
  status: VerificationStatus;
  score: number | null;
  uncertainty: number | null;
  passed: boolean | null;
  risk_score: number | null;
  grader_breakdown: Record<string, unknown>;
  latency_ms: number | null;
  created_at: string;
}

export interface AuditRecord {
  id: string;
  chain_index: number;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  occurred_at: string;
  prev_hash: string;
  record_hash: string;
}

// --- reward-hacking-detector models -----------------------------------------

export interface ConfidenceInterval {
  low: number;
  high: number;
}

export interface Evaluation {
  id: string;
  verifier_id: string;
  verifier_version: number;
  status: EvaluationStatus;
  seed: number;
  total_attacks: number;
  executed: number;
  errored: number;
  exploits_found: number;
  robustness_score: number | null;
  weighted_robustness_score: number | null;
  ci: ConfidenceInterval | null;
  error: string | null;
}

export interface Exploit {
  signature: string;
  verifier_id: string;
  verifier_version: number;
  category: ExploitCategory;
  strategy: string;
  severity: Severity;
  verifier_score: number;
  description: string;
  failure_reason: string;
  occurrences: number;
  artifact: unknown;
}

export interface Comparison {
  baseline_robustness: number;
  candidate_robustness: number;
  delta: number;
  is_regression: boolean;
  is_improvement: boolean;
  overlapping_ci: boolean;
  detail: string;
}

export interface Trend {
  verifier_id: string;
  direction: TrendDirection;
  history: number[];
}

export interface EvaluationReport {
  evaluation: Evaluation;
  seed: number;
  config: Record<string, unknown>;
  category_counts: Record<string, number>;
  exploits: Exploit[];
}

// --- request payloads -------------------------------------------------------

export interface SignupRequest {
  email: string;
  password: string;
  orgName: string;
  orgSlug: string;
  fullName?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  orgSlug?: string;
}

export interface CreateApiKeyOptions {
  role?: Role;
  projectId?: string;
}

export interface CreateProjectOptions {
  description?: string;
}

export interface ListVerificationsOptions {
  projectId?: string;
  verifierId?: string;
  limit?: number;
}

export interface LaunchEvaluationOptions {
  seedCases?: unknown[];
  seed?: number;
  maxAttacks?: number;
  enableModelAttacks?: boolean;
}

export interface SearchExploitsOptions {
  verifierId?: string;
  verifierVersion?: number;
  category?: ExploitCategory;
  severity?: Severity;
  strategy?: string;
  minScore?: number;
  q?: string;
  limit?: number;
  offset?: number;
}

export interface WaitOptions {
  /** Total time to wait before throwing, in milliseconds (default 60000). */
  timeoutMs?: number;
  /** Delay between polls, in milliseconds (default 500). */
  intervalMs?: number;
  /** Optional AbortSignal to cancel waiting. */
  signal?: AbortSignal;
}
