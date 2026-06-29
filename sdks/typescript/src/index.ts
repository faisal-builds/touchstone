/**
 * Touchstone TypeScript SDK — the official client for the AI Verification Layer.
 *
 * @packageDocumentation
 */

export { TouchstoneClient, type TouchstoneClientOptions } from "./client.js";
export { VERSION } from "./version.js";

export {
  TouchstoneError,
  AuthenticationError,
  PermissionDeniedError,
  NotFoundError,
  ConflictError,
  ValidationError,
  RateLimitError,
  ApiError,
  PollTimeoutError,
  errorForStatus,
  type ProblemJson,
  type ErrorMeta,
} from "./errors.js";

export { type FetchLike } from "./http.js";

export {
  InlineGuard,
  Blocked,
  type InlineAction,
  type InlineDecision,
  type StreamVerdict,
  type InlineGuardOptions,
  type CheckOptions,
  type EnforceOptions,
} from "./guard.js";

export {
  isTerminal,
  TERMINAL_STATUSES,
  type Role,
  type VerifierType,
  type VerificationStatus,
  type EvaluationStatus,
  type Severity,
  type ExploitCategory,
  type TrendDirection,
  type TokenPair,
  type ApiKey,
  type ApiKeyCreated,
  type Workspace,
  type Project,
  type Verifier,
  type Verification,
  type AuditRecord,
  type ConfidenceInterval,
  type Evaluation,
  type Exploit,
  type Comparison,
  type Trend,
  type EvaluationReport,
  type SignupRequest,
  type LoginRequest,
  type CreateApiKeyOptions,
  type CreateProjectOptions,
  type ListVerificationsOptions,
  type LaunchEvaluationOptions,
  type SearchExploitsOptions,
  type WaitOptions,
} from "./types.js";
