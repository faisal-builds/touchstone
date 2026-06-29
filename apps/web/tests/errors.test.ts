import { describe, expect, it } from "vitest";

import { ApiError, errorFromResponse } from "@/lib/api/errors";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("ApiError", () => {
  it("exposes auth and not-found helpers", () => {
    expect(new ApiError(401, "Unauthorized").isAuth).toBe(true);
    expect(new ApiError(404, "Not found").isNotFound).toBe(true);
    expect(new ApiError(500, "Server error").isAuth).toBe(false);
  });
});

describe("errorFromResponse", () => {
  it("maps problem+json title and detail", async () => {
    const err = await errorFromResponse(
      jsonResponse(403, { title: "Forbidden", detail: "You lack permission." }),
    );
    expect(err.status).toBe(403);
    expect(err.title).toBe("Forbidden");
    expect(err.detail).toBe("You lack permission.");
  });

  it("falls back to a message field when detail is absent", async () => {
    const err = await errorFromResponse(jsonResponse(400, { message: "Bad input" }));
    expect(err.detail).toBe("Bad input");
  });

  it("survives a non-JSON body", async () => {
    const res = new Response("not json", { status: 502, statusText: "Bad Gateway" });
    const err = await errorFromResponse(res);
    expect(err.status).toBe(502);
    expect(err.title).toBe("Bad Gateway");
  });
});
