"use server";

import { cookies } from "next/headers";

import { ADMIN_COOKIE, ADMIN_COOKIE_MAX_AGE_SECONDS } from "@/lib/admin-session";
import { ApiRequestError, createAdminProspectBatch, getAdminHealth } from "@/lib/api";

/**
 * `/admin/login`'s submit (contract §7.13). Verifies the typed token
 * against the API (`GET /admin/health` is the cheapest gated route), then
 * stores it in an httpOnly cookie. Navigation is left to the client (same
 * pattern as `LoginForm`), so this never has to `redirect()` from inside a
 * server action.
 */
export async function signInAdmin(
  token: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const trimmed = token.trim();
  if (!trimmed) {
    return { ok: false, error: "Enter the admin token." };
  }

  try {
    await getAdminHealth(trimmed);
  } catch (err) {
    if (err instanceof ApiRequestError && err.status === 403) {
      return { ok: false, error: "That token was not accepted." };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }

  const store = await cookies();
  store.set(ADMIN_COOKIE, trimmed, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: ADMIN_COOKIE_MAX_AGE_SECONDS,
  });

  return { ok: true };
}

export async function signOutAdmin(): Promise<void> {
  const store = await cookies();
  store.delete(ADMIN_COOKIE);
}

/**
 * `/admin/prospects`'s new-batch form. Splits the pasted text into
 * hostnames (whitespace or comma separated), then calls the API. Returns
 * the new batch id for the client to navigate to.
 */
export async function createProspectBatch(
  label: string,
  hostnamesText: string,
): Promise<{ ok: true; batchId: string } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  const trimmedLabel = label.trim();
  if (!trimmedLabel) return { ok: false, error: "Give the batch a label." };

  const hostnames = hostnamesText
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
  if (hostnames.length === 0) return { ok: false, error: "Add at least one hostname." };
  if (hostnames.length > 500) return { ok: false, error: "At most 500 hostnames per batch." };

  try {
    const batch = await createAdminProspectBatch(trimmedLabel, hostnames, token);
    return { ok: true, batchId: batch.batch_id };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}
