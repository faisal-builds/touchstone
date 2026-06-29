import "server-only";

import { cookies } from "next/headers";

import type { SessionInfo } from "./api/types";

/**
 * Session handling.
 *
 * The signed JWT issued by the control-plane is stored in an httpOnly cookie
 * (never exposed to client JS), alongside the org context needed to render the
 * shell. The active project is a separate, client-readable cookie so the project
 * switcher can update it without a round trip.
 */

const SESSION_COOKIE = process.env.SESSION_COOKIE_NAME || "ts_session";
const PROJECT_COOKIE = "ts_project";

interface SessionPayload extends SessionInfo {
  token: string;
}

function encode(p: SessionPayload): string {
  return Buffer.from(JSON.stringify(p), "utf8").toString("base64url");
}

function decode(raw: string): SessionPayload | null {
  try {
    return JSON.parse(Buffer.from(raw, "base64url").toString("utf8")) as SessionPayload;
  } catch {
    return null;
  }
}

export function setSession(p: SessionPayload, maxAgeSeconds: number): void {
  cookies().set(SESSION_COOKIE, encode(p), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: maxAgeSeconds,
  });
}

export function clearSession(): void {
  cookies().delete(SESSION_COOKIE);
  cookies().delete(PROJECT_COOKIE);
}

function readSession(): SessionPayload | null {
  const raw = cookies().get(SESSION_COOKIE)?.value;
  return raw ? decode(raw) : null;
}

export function getSession(): SessionInfo | null {
  const s = readSession();
  if (!s) return null;
  return { orgId: s.orgId, orgSlug: s.orgSlug, email: s.email };
}

export function getToken(): string | null {
  return readSession()?.token ?? null;
}

export function getActiveProject(): string | null {
  return cookies().get(PROJECT_COOKIE)?.value ?? null;
}

export function setActiveProject(projectId: string): void {
  cookies().set(PROJECT_COOKIE, projectId, {
    httpOnly: false,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}
