import { describe, expect, it } from "vitest";

import {
  ApiError,
  AuthenticationError,
  ConflictError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  TouchstoneError,
  ValidationError,
  errorForStatus,
} from "../src/errors.js";

describe("errorForStatus", () => {
  it("maps known statuses to typed subclasses", () => {
    expect(errorForStatus(401, {})).toBeInstanceOf(AuthenticationError);
    expect(errorForStatus(403, {})).toBeInstanceOf(PermissionDeniedError);
    expect(errorForStatus(404, {})).toBeInstanceOf(NotFoundError);
    expect(errorForStatus(409, {})).toBeInstanceOf(ConflictError);
    expect(errorForStatus(422, {})).toBeInstanceOf(ValidationError);
  });

  it("maps 5xx and unknown statuses to ApiError", () => {
    expect(errorForStatus(500, {})).toBeInstanceOf(ApiError);
    expect(errorForStatus(418, {})).toBeInstanceOf(ApiError);
  });

  it("every error is a TouchstoneError and carries status + detail", () => {
    const err = errorForStatus(404, { detail: "verifier not found", type: "about:blank" });
    expect(err).toBeInstanceOf(TouchstoneError);
    expect(err.status).toBe(404);
    expect(err.detail).toBe("verifier not found");
    expect(err.typeUri).toBe("about:blank");
    expect(err.message).toBe("verifier not found");
  });

  it("falls back to title then a generic message", () => {
    expect(errorForStatus(404, { title: "Not Found" }).detail).toBe("Not Found");
    expect(errorForStatus(404, {}).detail).toBe("HTTP 404");
  });

  it("attaches retryAfter to RateLimitError", () => {
    const err = errorForStatus(429, { detail: "slow down" }, 30);
    expect(err).toBeInstanceOf(RateLimitError);
    expect((err as RateLimitError).retryAfter).toBe(30);
  });

  it("instanceof works across the hierarchy", () => {
    const err = errorForStatus(409, { detail: "taken" });
    expect(err instanceof ConflictError).toBe(true);
    expect(err instanceof TouchstoneError).toBe(true);
    expect(err instanceof Error).toBe(true);
  });
});
