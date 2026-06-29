/**
 * Typed API errors. The backend returns RFC-7807 problem+json on failure; we map
 * that into a single ApiError the UI can branch on (status, title, detail).
 */

export interface ProblemJson {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string | undefined;

  constructor(status: number, title: string, detail?: string) {
    super(detail || title);
    this.name = "ApiError";
    this.status = status;
    this.title = title;
    this.detail = detail;
  }

  get isAuth(): boolean {
    return this.status === 401;
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export async function errorFromResponse(res: Response): Promise<ApiError> {
  let body: ProblemJson = {};
  try {
    body = (await res.json()) as ProblemJson;
  } catch {
    // Non-JSON error body; fall back to status text.
  }
  const title = body.title || res.statusText || "Request failed";
  const detail =
    body.detail ||
    (typeof body["message"] === "string" ? (body["message"] as string) : undefined);
  return new ApiError(res.status, title, detail);
}
