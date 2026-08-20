import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Gate C: standalone output is what apps/web/Dockerfile.prod copies into
  // its lean runtime stage — a self-contained server bundle with only the
  // dependencies actually used, not the full node_modules tree.
  output: "standalone",
  // Gate E follow-up: production once shipped a build where `/` (app/page.tsx)
  // and `/app` (app/app/page.tsx) resolved to the same numeric module id in
  // the same server chunk, so the dashboard silently overwrote the homepage
  // and every route redirect-looped to /login. Webpack's default production
  // `moduleIds: "deterministic"` assigns short numeric ids by hashing each
  // module's resource path — plausible to collide for two paths this close
  // ("app/page" vs "app/app/page"). "named" uses the literal path string as
  // the id instead, which cannot collide the same way. Named ids are
  // slightly larger in the bundle; irrelevant next to correctness here.
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.optimization.moduleIds = "named";
    }
    return config;
  },
};

// Gate C item 5: no-op whenever SENTRY_ORG/SENTRY_PROJECT aren't set (source
// map upload needs a Sentry auth token at build time; error reporting
// itself only needs NEXT_PUBLIC_SENTRY_DSN at runtime, set separately in
// the sentry.*.config.ts files). silent avoids failing the build over a
// missing upload token in environments that don't have one configured.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: true,
  widenClientFileUpload: true,
  disableLogger: true,
  automaticVercelMonitors: false,
});
