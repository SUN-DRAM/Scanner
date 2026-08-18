"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, updateCurrentOrg } from "@/lib/api";
import type { DigestMode, Organisation } from "@/types/contract";

interface QuietHoursFormProps {
  org: Organisation;
}

/** §7.12: PATCH /orgs/current's alert-preference fields — timezone, quiet
 * hours window, and digest mode/hour. Only the fields actually changed are
 * sent (the backend only applies keys present in the request either way,
 * but there's no reason to resend everything on every save). */
export function QuietHoursForm({ org }: QuietHoursFormProps) {
  const router = useRouter();
  const [timezone, setTimezone] = useState(org.timezone);
  const [quietStart, setQuietStart] = useState(org.quiet_hours_start);
  const [quietEnd, setQuietEnd] = useState(org.quiet_hours_end);
  const [digestMode, setDigestMode] = useState<DigestMode>(org.digest_mode);
  const [digestHour, setDigestHour] = useState(org.digest_hour);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setSaved(false);
    try {
      await updateCurrentOrg({
        timezone,
        quiet_hours_start: quietStart,
        quiet_hours_end: quietEnd,
        digest_mode: digestMode,
        digest_hour: digestHour,
      });
      setSaved(true);
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.message : "Could not save your changes.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex max-w-reading flex-col gap-4">
      <label className="flex flex-col gap-1 text-sm text-ink">
        Timezone (IANA name, e.g. Asia/Kolkata)
        <Input
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
          placeholder="Asia/Kolkata"
        />
      </label>

      <div className="flex gap-4">
        <label className="flex flex-1 flex-col gap-1 text-sm text-ink">
          Quiet hours start
          <Input
            type="time"
            value={quietStart}
            onChange={(event) => setQuietStart(event.target.value)}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm text-ink">
          Quiet hours end
          <Input
            type="time"
            value={quietEnd}
            onChange={(event) => setQuietEnd(event.target.value)}
          />
        </label>
      </div>
      <p className="text-xs text-ink-muted">
        Non-urgent alerts wait until quiet hours end. A certificate expiring in 3 days or less, and
        a scan failure, always send right away.
      </p>

      <label className="flex flex-col gap-1 text-sm text-ink">
        Delivery
        <select
          value={digestMode}
          onChange={(event) => setDigestMode(event.target.value as DigestMode)}
          className="h-12 rounded-control border border-line bg-surface px-4 text-base text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cobalt"
        >
          <option value="immediate">Send each alert immediately</option>
          <option value="digest">Batch non-urgent alerts into a daily digest</option>
        </select>
      </label>

      {digestMode === "digest" ? (
        <label className="flex flex-col gap-1 text-sm text-ink">
          Digest hour (0–23, local time)
          <Input
            type="number"
            min={0}
            max={23}
            value={digestHour}
            onChange={(event) => setDigestHour(Number(event.target.value))}
            className="max-w-[120px]"
          />
        </label>
      ) : null}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? "Saving" : "Save"}
        </Button>
        {saved ? <span className="text-sm text-pass">Saved.</span> : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
