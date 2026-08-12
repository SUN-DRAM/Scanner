/**
 * Gate C item 5: Sentry error tracking for the Node.js server runtime
 * (SSR, route handlers, the OG-image route). Guarded by
 * NEXT_PUBLIC_SENTRY_DSN — see sentry.client.config.ts for why the same
 * (non-secret, write-only) DSN is reused server-side rather than adding a
 * second env var.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
});
