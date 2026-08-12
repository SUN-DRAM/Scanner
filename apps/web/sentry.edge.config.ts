/**
 * Gate C item 5: Sentry error tracking for the Edge runtime (middleware,
 * if any is ever added). Guarded by NEXT_PUBLIC_SENTRY_DSN, same as
 * sentry.client.config.ts / sentry.server.config.ts.
 */
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? "production",
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
});
