"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { signInAdmin } from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function AdminLoginForm() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting || token.trim().length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await signInAdmin(token);
      if (result.ok) {
        router.push("/admin/accounts");
        router.refresh();
        return;
      }
      setError(result.error);
    } catch {
      setError("Could not reach the API. Try again.");
    }
    setSubmitting(false);
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-4">
      <Input
        type="password"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        placeholder="Operator token"
        aria-label="Admin token"
        autoComplete="off"
        autoFocus
        disabled={submitting}
        className="font-mono"
      />
      <Button type="submit" disabled={submitting || token.trim().length === 0}>
        {submitting ? "Checking" : "Continue"}
      </Button>
      {error ? (
        <p role="alert" className="text-sm text-alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
