import type { MetadataRoute } from "next";

import { codeToSlug, FINDINGS_CATALOGUE } from "@/lib/findings-catalogue";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

// `/scan/[slug]` pages are per-visitor scan results, not evergreen content —
// there's no listing of them to enumerate, and they shouldn't be indexed as
// if they were. Only the static/content routes belong in the sitemap.
const GUIDE_SLUGS = [
  "100-day-certificate-2027",
  "ssl-certificate-expiry-monitoring",
  "nginx-auto-ssl-renewal",
  "certbot-alternative-docker",
  "free-ssl-checker-india",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: SITE_URL, changeFrequency: "daily", priority: 1 },
    { url: `${SITE_URL}/countdown`, changeFrequency: "daily", priority: 0.8 },
    { url: `${SITE_URL}/guides`, changeFrequency: "weekly", priority: 0.6 },
    ...GUIDE_SLUGS.map((slug) => ({
      url: `${SITE_URL}/guides/${slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.7,
    })),
    ...FINDINGS_CATALOGUE.map((entry) => ({
      url: `${SITE_URL}/docs/findings/${codeToSlug(entry.code)}`,
      changeFrequency: "monthly" as const,
      priority: 0.3,
    })),
  ];
}
