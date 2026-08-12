"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, submitWaitlist } from "@/lib/api";

interface WaitlistFormProps {
  scanId: string;
  hostname: string;
}

/** Gate B item 1: the one piece of funnel capture on the result page — an
 * inline field, not a modal or interstitial, that the visitor can ignore
 * entirely and still get their scan result. */
export function WaitlistForm({ scanId, hostname }: WaitlistFormProps) {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmedMessage, setConfirmedMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const response = await submitWaitlist({ scan_id: scanId, email: trimmed });
      setConfirmedMessage(response.message);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiRequestError) {
        setError(err.message);
      } else {
        setError("Could not reach the scanner. Check your connection and try again.");
      }
    }
  }

  if (confirmedMessage) {
    return (
      <div className="rounded-card border border-line bg-cobalt-soft p-4 text-center">
        <p className="text-sm text-ink">{confirmedMessage}</p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-reading">
      <p className="mb-3 text-center text-sm text-ink-muted">
        Get alerted before this certificate expires.
      </p>
      <div className="flex flex-col gap-3 rounded-card border border-line bg-surface p-2 sm:flex-row sm:items-center">
        <Input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@company.com"
          aria-label={`Email address to alert before ${hostname} expires`}
          autoComplete="email"
          disabled={submitting}
          className="h-11 border-0 px-4 focus-visible:ring-0"
        />
        <Button type="submit" disabled={submitting || email.trim().length === 0}>
          {submitting ? "Submitting" : "Notify me"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-center text-sm text-alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
