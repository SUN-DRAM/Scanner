import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Gate C: standalone output is what apps/web/Dockerfile.prod copies into
  // its lean runtime stage — a self-contained server bundle with only the
  // dependencies actually used, not the full node_modules tree.
  output: "standalone",
  // Gate E follow-up: production once shipped a build where `/`
  // (app/page.tsx) rendered app/app/page.tsx's dashboard instead — every
  // route redirect-looped to /login. Root cause: Next's app-router tree
  // builder, in this exact build pipeline, mis-resolved routes when a
  // segment folder was literally named "app" directly inside the App
  // Router's own "app" root (self-nested same-name directory) — confirmed
  // by renaming apps/web/app/app -> apps/web/app/dashboard, which alone
  // fixed it. The rewrite below keeps the public URL at /app/* unchanged.
  // `moduleIds: "named"` is kept alongside as defense in depth — it forces
  // webpack's production module ids to be the literal resource path string
  // instead of a short numeric hash, which independently ruled out one way
  // two close paths could ever share an id, even though the folder rename
  // turned out to be the fix that actually mattered here.
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.optimization.moduleIds = "named";
    }
    return config;
  },
  async rewrites() {
    return [
      { source: "/app", destination: "/dashboard" },
      { source: "/app/:path*", destination: "/dashboard/:path*" },
    ];
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
