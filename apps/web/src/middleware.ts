import { NextRequest, NextResponse } from "next/server";

/**
 * Route guard. Unauthenticated users are sent to /login; authenticated users are
 * kept out of the auth pages. Session presence is detected by the httpOnly
 * cookie (its contents are validated server-side on every API call).
 */

const COOKIE = process.env.SESSION_COOKIE_NAME || "ts_session";
const AUTH_PAGES = ["/login", "/signup"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const authed = Boolean(req.cookies.get(COOKIE)?.value);
  const onAuthPage = AUTH_PAGES.some((p) => pathname === p);

  if (!authed && !onAuthPage) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (authed && onAuthPage) {
    const url = req.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Guard everything except API routes, static assets, and the favicon.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|assets).*)"],
};
