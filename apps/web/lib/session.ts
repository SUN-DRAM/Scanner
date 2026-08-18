/**
 * Server-only auth helpers for the dashboard (Phase 2 §7.6). `next/headers`
 * only works inside a Server Component, so it's confined to this file —
 * never imported from `lib/api.ts` itself, which a "use client" component
 * also imports (see `lib/api.ts`'s `AuthedRequestOptions` comment).
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiRequestError, getCurrentOrg, getMe } from "@/lib/api";
import type { Organisation, User } from "@/types/contract";

/** The current request's cookies, forwarded verbatim to an authenticated
 * API call — never parsed or trusted client-side, only handed back to the
 * API for it to verify (`app/sessions.py` does the actual signature check). */
export async function getForwardedCookie(): Promise<string> {
  const cookieStore = await cookies();
  return cookieStore.toString();
}

/** Redirects to /login if the request has no valid session. Every /app
 * page (via app/app/layout.tsx) goes through this once, so no individual
 * page has to repeat the check. */
export async function requireUser(): Promise<{ cookie: string; me: User }> {
  const cookie = await getForwardedCookie();
  try {
    const me = await getMe(cookie);
    return { cookie, me };
  } catch (err) {
    if (err instanceof ApiRequestError && err.code === "UNAUTHENTICATED") {
      redirect("/login");
    }
    throw err;
  }
}

export async function requireOrg(): Promise<{ cookie: string; me: User; org: Organisation }> {
  const { cookie, me } = await requireUser();
  const org = await getCurrentOrg(cookie);
  return { cookie, me, org };
}
