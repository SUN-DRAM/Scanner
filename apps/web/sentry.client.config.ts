/**
 * Gate C item 5: Sentry error tracking for the browser bundle, guarded
 * entirely by NEXT_PUBLIC_SENTRY_DSN — unset means Sentry.init runs with an
 * empty DSN, which the SDK treats as disabled rather than an error.
 *
 * DPDP posture (CLAUDE.md rule 10): no session replay, no PII-capturing
 * integrations. The frontend never handles raw client IPs itself (the API
 * hashes them server-side, contract §11), and this file doesn't change that.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
});
