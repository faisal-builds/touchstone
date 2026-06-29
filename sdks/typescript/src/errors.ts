/**
 * Typed errors for the Touchstone SDK.
 *
 * The API returns `application/problem+json` (RFC 7807) on failure. The client
 * parses that body and throws the matching error subclass, so callers can
 * `catch`/`instanceof NotFoundError` rather than inspecting status codes. Every
 * error carries the problem `detail`, the originating `status`, and the
 * problem `type` URI when present.
 */

export interface ProblemJson {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  [key: string]: unknown;
}

export interface ErrorMeta {
  status?: number;
  typeUri?: string;
  body?: ProblemJson;
}

export class TouchstoneError extends Error {
  readonly status: number | undefined;
  readonly typeUri: string | undefined;
  readonly body: ProblemJson;

  constructor(detail: string, meta: ErrorMeta = {}) {
    super(detail);
    this.name = new.target.name;
    this.detail = detail;
    this.status = meta.status;
    this.typeUri = meta.typeUri;
    this.body = meta.body ?? {};
    // Restore the prototype chain when targeting ES5-ish runtimes.
    Object.setPrototypeOf(this, new.target.prototype);
  }

  readonly detail: string;
}

/** 401 — missing or invalid credentials. */
export class AuthenticationError extends TouchstoneError {}

/** 403 — authenticated but not permitted. */
export class PermissionDeniedError extends TouchstoneError {}

/** 404 — resource does not exist. */
export class NotFoundError extends TouchstoneError {}

/** 409 — duplicate or conflicting resource (e.g. email or slug taken). */
export class ConflictError extends TouchstoneError {}

/** 422 — request failed validation. */
export class ValidationError extends TouchstoneError {}

/** 429 — rate limited; `retryAfter` is seconds, when the server provides it. */
export class RateLimitError extends TouchstoneError {
  readonly retryAfter: number | undefined;
  constructor(detail: string, meta: ErrorMeta & { retryAfter?: number } = {}) {
    super(detail, meta);
    this.retryAfter = meta.retryAfter;
  }
}

/** 5xx or any otherwise-unmapped status. */
export class ApiError extends TouchstoneError {}

/** Raised by the `waitFor*` polling helpers when the deadline elapses. */
export class PollTimeoutError extends TouchstoneError {}

const STATUS_MAP: Record<number, new (detail: string, meta?: ErrorMeta) => TouchstoneError> = {
  401: AuthenticationError,
  403: PermissionDeniedError,
  404: NotFoundError,
  409: ConflictError,
  422: ValidationError,
};

export function errorForStatus(
  status: number,
  body: ProblemJson,
  retryAfter?: number,
): TouchstoneError {
  const detail =
    body.detail ||
    body.title ||
    (typeof body["message"] === "string" ? (body["message"] as string) : undefined) ||
    `HTTP ${status}`;
  const meta: ErrorMeta = { status, typeUri: body.type, body };

  if (status === 429) {
    return new RateLimitError(detail, { ...meta, retryAfter });
  }
  const Cls = STATUS_MAP[status] ?? ApiError;
  return new Cls(detail, meta);
}
