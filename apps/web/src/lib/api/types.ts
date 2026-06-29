/**
 * API types — mirror the control-plane and reward-hacking-detector response
 * shapes. Kept in one place so the rest of the app is fully typed against the
 * backend contracts.
 */

export interface TokenPair {
  access_token: string;
  token_type: string;
  expires_in: number;
  org_id: string;
  org_slug: string;
}

export type Role = "owner" | "admin" | "member" | "viewer" | "service";

export interface ApiKey {
  id: string;
  name: string;
  key_id: string;
  role: Role;
  project_id: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface Workspace {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
}

export interface Project {
  id: string;
  organization_id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
}

export type VerifierType = "code" | "model" | "process" | "hybrid";

export interface Verifier {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  version: number;
  verifier_type: VerifierType;
  robustness_score: number | null;
  is_active: boolean;
}

export type VerificationStatus =
  | "pending" | "running" | "completed" | "failed";

export interface Verification {
  id: string;
  project_id: string;
  verifier_id: string;
  status: VerificationStatus;
  score: number | null;
  uncertainty: number | null;
  passed: boolean | null;
  risk_score: number | null;
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

// --- Reward-hacking detector ------------------------------------------------

export type EvaluationStatus = "pending" | "running" | "completed" | "failed";

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

export type Severity = "low" | "medium" | "high" | "critical";

export type ExploitCategory =
  | "content_corruption" | "judge_manipulation" | "length_bias"
  | "formatting_exploit" | "edge_case" | "model_generated";

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
  direction: "improving" | "declining" | "stable" | "insufficient_data";
  history: number[];
}

export interface EvaluationReport {
  evaluation: Evaluation;
  seed: number;
  config: Record<string, unknown>;
  category_counts: Record<string, number>;
  exploits: Exploit[];
}

export interface SessionInfo {
  orgId: string;
  orgSlug: string;
  email: string;
}
