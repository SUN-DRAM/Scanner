import type { Metadata } from "next";

import { GuideCta } from "@/components/scan/GuideCta";

export const metadata: Metadata = {
  title: "Free SSL checker for Indian websites",
  description:
    "A free, no-signup SSL and DNS checker built for founders and agencies in India managing certificates ahead of the 2027 lifetime cut.",
};

export default function FreeSslCheckerIndiaGuide() {
  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="text-sm font-medium text-cobalt">Guide</p>
      <h1 className="mt-2 font-display text-xl leading-display text-ink sm:text-2xl md:text-3xl">
        A free SSL checker built for Indian founders and agencies
      </h1>
      <p className="mt-4 text-ink-muted">
        Most SSL checkers are built for security teams. SUN-DRAM Scanner is built for someone
        running 15–60 hostnames who has never had to think about certificate lifetimes before — and
        is about to have to.
      </p>

      <article className="prose-content mt-10 leading-prose text-ink">
        <h2>What it checks</h2>
        <p>
          One scan covers the TLS certificate and its expiry, the certificate chain, which TLS
          protocol versions and ciphers are enabled, DNS and domain registration, email
          authentication (SPF, DMARC, DKIM), and the security headers the site sends. It also gives
          a direct readiness verdict against the CA/Browser Forum&apos;s certificate lifetime
          changes — 100 days from March 2027, 47 days from March 2029.
        </p>

        <h2>No signup, no cost, no history held against you</h2>
        <p>
          There&apos;s no account to create and nothing to pay. Enter a hostname, get a graded
          report in under 20 seconds, and share the result as a link — useful for an agency
          reporting back to a client, or a founder getting a second opinion from whoever manages
          their infrastructure.
        </p>

        <h2>Built with India&apos;s data protection law in mind</h2>
        <p>
          This is a public scanner that accepts hostnames from anyone, so it has to be careful by
          default: it only makes read-only TLS handshakes and HTTP requests, never anything that
          writes or authenticates. In line with the DPDP Act, the IP address making a scan request
          is never stored raw — it&apos;s hashed before anything touches a database.
        </p>

        <h2>Why this matters right now</h2>
        <p>
          Certificate maximum lifetimes are already down to 200 days as of March 2026, dropping to
          100 days in March 2027. Any hostname still relying on a manually issued, long-lived
          certificate is on borrowed time — and the fix (moving to an automated ACME client) takes
          minutes to identify but is easy to keep putting off without a clear signal that it&apos;s
          actually needed.
        </p>
      </article>

      <GuideCta />
    </main>
  );
}
