"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, createScan } from "@/lib/api";

export function ScanForm() {
  const router = useRouter();
  const [hostname, setHostname] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = hostname.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      const response = await createScan({ hostname: trimmed });
      router.push(`/scan/${response.public_slug}`);
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiRequestError) {
        setError(err.message);
      } else {
        setError("Could not reach the scanner. Check your connection and try again.");
      }
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-reading">
      <div className="flex flex-col gap-3 rounded-card border border-line bg-surface p-2 shadow-sm sm:flex-row sm:items-center">
        <Input
          value={hostname}
          onChange={(event) => setHostname(event.target.value)}
          placeholder="example.com"
          aria-label="Hostname to scan"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          disabled={submitting}
          className="h-12 border-0 px-4 text-base focus-visible:ring-0 sm:h-14 sm:text-lg"
        />
        <Button
          type="submit"
          disabled={submitting || trimmedIsEmpty(hostname)}
          className="sm:h-14 sm:px-8"
        >
          {submitting ? "Scanning" : "Scan"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function trimmedIsEmpty(value: string): boolean {
  return value.trim().length === 0;
}
