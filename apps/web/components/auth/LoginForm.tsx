"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiRequestError, requestOtp, verifyOtp } from "@/lib/api";

type Step = "email" | "code";

/** /login (contract §Step 7): "one email field, then one code field.
 * Nothing else on the page." Email OTP only — no password field exists
 * anywhere in this form (§7.6). */
export function LoginForm() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRequestCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await requestOtp(trimmed);
      setStep("code");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await verifyOtp({ email: email.trim(), code: trimmed });
      router.push("/app");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  if (step === "email") {
    return (
      <form onSubmit={handleRequestCode} className="flex w-full flex-col gap-4">
        <Input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@company.com"
          aria-label="Email address"
          autoComplete="email"
          autoFocus
          disabled={submitting}
        />
        <Button type="submit" disabled={submitting || email.trim().length === 0}>
          {submitting ? "Sending code" : "Send code"}
        </Button>
        {error ? (
          <p role="alert" className="text-center text-sm text-alert">
            {error}
          </p>
        ) : null}
      </form>
    );
  }

  return (
    <form onSubmit={handleVerifyCode} className="flex w-full flex-col gap-4">
      <p className="text-center text-sm text-ink-muted">
        We sent a 6-digit code to <span className="font-medium text-ink">{email}</span>.
      </p>
      <Input
        value={code}
        onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
        placeholder="123456"
        inputMode="numeric"
        aria-label="6-digit code"
        autoComplete="one-time-code"
        autoFocus
        disabled={submitting}
        className="text-center font-mono text-lg tracking-[0.3em]"
      />
      <Button type="submit" disabled={submitting || code.trim().length !== 6}>
        {submitting ? "Verifying" : "Verify code"}
      </Button>
      <button
        type="button"
        onClick={() => {
          setStep("email");
          setCode("");
          setError(null);
        }}
        className="text-center text-sm text-ink-muted hover:text-ink hover:underline"
      >
        Use a different email
      </button>
      {error ? (
        <p role="alert" className="text-center text-sm text-alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiRequestError) return err.message;
  return "Could not reach the scanner. Check your connection and try again.";
}
