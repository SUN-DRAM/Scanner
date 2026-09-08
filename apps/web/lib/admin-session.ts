/**
 * Server-only helpers for the internal admin console (contract §7.13).
 *
 * The operator's `ADMIN_TOKEN` is held in an httpOnly `sd_admin` cookie,
 * set by the `/admin/login` server action once it verifies against the API.
 * The web app never contains the token itself — it forwards whatever the
 * operator typed and lets the API be the sole judge.
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiRequestError } from "@/lib/api";

export const ADMIN_COOKIE = "sd_admin";
/** 12 hours — short, because this is a shared credential on a machine the
 * operator controls. Re-entering the token is cheap. */
export const ADMIN_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 12;

export async function getAdminToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(ADMIN_COOKIE)?.value ?? null;
}

/** Redirects to /admin/login when no token cookie is present. Each page
 * still needs to catch a 403 from its own API call (the token may have been
 * revoked or changed since it was set) — see `redirectIfForbidden`. */
export async function requireAdminToken(): Promise<string> {
  const token = await getAdminToken();
  if (!token) {
    redirect("/admin/login");
  }
  return token;
}

export function redirectIfForbidden(err: unknown): never {
  if (err instanceof ApiRequestError && err.status === 403) {
    redirect("/admin/login");
  }
  throw err;
}
