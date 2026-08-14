import type { Metadata } from "next";
import Link from "next/link";

import { GuideCta } from "@/components/scan/GuideCta";

export const metadata: Metadata = {
  title: "SSL certificate expiry monitoring — free automated checker",
  description:
    "Why manual certificate tracking fails, what proper expiry monitoring actually checks, and a free tool to see where you stand right now.",
  alternates: { canonical: "/guides/ssl-certificate-expiry-monitoring" },
};

export default function SslExpiryMonitoringGuide() {
  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="text-sm font-medium text-cobalt">Guide</p>
      <h1 className="mt-2 font-display text-xl leading-display text-ink sm:text-2xl md:text-3xl">
        SSL certificate expiry monitoring, done properly
      </h1>
      <p className="mt-4 text-ink-muted">
        Most certificate outages aren&apos;t caused by an attack. They&apos;re caused by nobody
        noticing a date on a calendar until browsers started refusing connections.
      </p>

      <article className="prose-content mt-10 leading-prose text-ink">
        <h2>Why manual tracking fails</h2>
        <p>
          A spreadsheet with expiry dates works right up until someone leaves the company, a
          calendar reminder gets snoozed once too often, or a new hostname goes live without anyone
          adding it to the list. Certificate expiry monitoring that depends on a human remembering
          is monitoring that will eventually fail — not because anyone was careless, but because
          it&apos;s the kind of task that&apos;s invisible until the exact moment it isn&apos;t.
        </p>

        <h2>What proper monitoring actually checks</h2>
        <p>
          Expiry date is the obvious one, but it&apos;s not the only thing that silently breaks a
          site. A complete check covers:
        </p>
        <ul>
          <li>Days until expiry, with enough lead time to catch a failed renewal attempt</li>
          <li>Whether the full certificate chain is served, not just the leaf certificate</li>
          <li>Whether the certificate actually covers the hostname being checked</li>
          <li>Domain registration expiry — a lapsed domain takes down everything at once</li>
          <li>Whether the renewal process looks automated, or is quietly still manual</li>
        </ul>

        <h2>Automated monitoring, not automated renewal</h2>
        <p>
          A scanner and a renewal tool solve different problems. An ACME client like Certbot renews
          certificates; a scanner tells you whether that renewal actually worked, whether the chain
          is complete, and whether anything else about the TLS setup needs attention — regardless of
          which tool issued the certificate in the first place. Both matter: automation that
          silently stops working is exactly what expiry monitoring exists to catch.
        </p>

        <h2>Check any hostname free</h2>
        <p>
          SUN-DRAM Scanner runs a full TLS and DNS check — certificate, chain, protocol support,
          security headers, email authentication, and a specific read on whether this hostname is
          ready for the CA/Browser Forum&apos;s{" "}
          <Link href="/guides/100-day-certificate-2027">100-day certificate lifetime cut</Link> in
          March 2027. No signup, no cost, and the result is a link you can share with anyone.
        </p>
      </article>

      <GuideCta />
    </main>
  );
}
