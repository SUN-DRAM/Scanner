/**
 * Next.js's own instrumentation hook (stable since Next 14, no config flag
 * needed) — the standard place @sentry/nextjs's server/edge configs get
 * registered from. `sentry.client.config.ts` is wired in separately by the
 * Sentry webpack plugin (see next.config.ts's withSentryConfig), not here.
 * `Sentry.init` itself is a no-op whenever NEXT_PUBLIC_SENTRY_DSN is unset
 * (see the sentry.*.config.ts files), so nothing here needs its own guard.
 */
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export const onRequestError = Sentry.captureRequestError;
