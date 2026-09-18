"use server";

import { cookies } from "next/headers";

import { ADMIN_COOKIE, ADMIN_COOKIE_MAX_AGE_SECONDS } from "@/lib/admin-session";
import {
  ApiRequestError,
  createAdminProspectBatch,
  createOutreachCampaign,
  getAdminHealth,
  getOutreachScanProgress,
  importOutreachCampaignCsv,
  pauseOutreachScan,
  resumeOutreachScan,
  startOutreachScan,
} from "@/lib/api";
import type { OutreachImportReport, OutreachScanProgress } from "@/types/contract";

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

/**
 * `/admin/outreach`'s new-campaign form (contract §7.15, v3.6). A campaign
 * is created empty — CSV import happens on its own detail page.
 */
export async function createCampaign(
  name: string,
): Promise<{ ok: true; campaignId: string } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  const trimmed = name.trim();
  if (!trimmed) return { ok: false, error: "Give the campaign a name." };

  try {
    const campaign = await createOutreachCampaign(trimmed, token);
    return { ok: true, campaignId: campaign.campaign_id };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}

/**
 * `/admin/outreach/[campaign_id]`'s CSV upload form. Bound to a native
 * `<form action={...}>`, so `formData` arrives already populated by the
 * browser — no client-side JSON assembly needed for the file itself.
 */
export async function importOutreachCsv(
  campaignId: string,
  formData: FormData,
): Promise<{ ok: true; report: OutreachImportReport } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return { ok: false, error: "Choose a CSV file first." };
  }

  try {
    const report = await importOutreachCampaignCsv(campaignId, file, token);
    return { ok: true, report };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}

/**
 * `/admin/outreach/[campaign_id]`'s Start/Resume scan button (contract
 * §7.16, v3.9/v3.10). Neither action enqueues anything itself — the
 * outreach orchestrator's own periodic tick picks up a `running` campaign
 * within `OUTREACH_SCAN_DELAY_SECONDS` — so the caller shouldn't expect an
 * immediate visible effect, only an accepted state change.
 */
export async function startScan(
  campaignId: string,
  includeWeak: boolean,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  try {
    await startOutreachScan(campaignId, includeWeak, token);
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}

export async function pauseScan(
  campaignId: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  try {
    await pauseOutreachScan(campaignId, token);
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}

export async function resumeScan(
  campaignId: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return { ok: false, error: "Session expired — sign in again." };

  try {
    await resumeOutreachScan(campaignId, token);
    return { ok: true };
  } catch (err) {
    if (err instanceof ApiRequestError) {
      return { ok: false, error: err.status === 403 ? "Not authorised." : err.message };
    }
    return { ok: false, error: "Could not reach the API. Try again." };
  }
}

/**
 * Polled by `ScanProgressPanel` (client component) every few seconds —
 * "poll the progress endpoint; no websockets" (stage prompt's own words).
 * Returns `null` on any failure so the poller can show "couldn't refresh"
 * without tearing down whatever it last rendered successfully.
 */
export async function getScanProgress(campaignId: string): Promise<OutreachScanProgress | null> {
  const token = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!token) return null;

  try {
    return await getOutreachScanProgress(campaignId, token);
  } catch {
    return null;
  }
}
