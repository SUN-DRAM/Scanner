import type { Metadata } from "next";
import Link from "next/link";

import { GuideCta } from "@/components/scan/GuideCta";
import { getDeadlines } from "@/lib/api";
import { formatIsoDateDisplay } from "@/lib/format";

export const metadata: Metadata = {
  title: "100-day certificates in 2027 — what changes and how to prepare",
  description:
    "From 15 March 2027 the CA/Browser Forum caps new TLS certificates at 100 days. Here's what's actually changing, why, and how to be ready.",
  alternates: { canonical: "/guides/100-day-certificate-2027" },
};

export default async function HundredDayCertificate2027Guide() {
  const deadlines = await getDeadlines();

  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="text-sm font-medium text-cobalt">Guide</p>
      <h1 className="mt-2 font-display text-xl leading-display text-ink sm:text-2xl md:text-3xl">
        The 100-day certificate rule, and what it actually means
      </h1>
      <p className="mt-4 text-ink-muted">
        {deadlines.next_deadline.days_remaining} days until maximum TLS certificate lifetime drops
        to 100 days, on {formatIsoDateDisplay(deadlines.next_deadline.date)}.
      </p>

      <article className="prose-content mt-10 leading-prose text-ink">
        <h2>What&apos;s changing</h2>
        <p>
          The CA/Browser Forum — the group of certificate authorities and browser makers that sets
          the rules every public TLS certificate has to follow — is phasing maximum certificate
          lifetimes down in stages: 200 days from 15 March 2026, 100 days from 15 March 2027, and 47
          days from 15 March 2029. After each date, no publicly trusted certificate authority can
          issue a certificate longer than the new cap, for anyone.
        </p>

        <h2>Why it&apos;s happening</h2>
        <p>
          A shorter-lived certificate has a shorter window to do damage if something goes wrong with
          it — a misissuance, a compromised private key, an outdated domain validation record. It
          also forces something the industry has wanted for years: certificate renewal that&apos;s
          automated rather than manual, since nobody is going to reissue a certificate by hand every
          47 days at any real scale.
        </p>

        <h2>What breaks if you&apos;re not ready</h2>
        <p>
          Nothing breaks on 15 March 2027 itself for a certificate already issued before then —
          existing certificates keep running until their own expiry. What breaks is the next
          renewal: a certificate authority simply won&apos;t issue a 200-day or 398-day certificate
          anymore. Any renewal process built around long lifetimes and manual issuance stops working
          at exactly the moment it&apos;s relied on.
        </p>

        <h2>How to be ready</h2>
        <p>
          The fix is the same regardless of how much lifetime is left: move to an automated ACME
          client — Certbot, acme.sh, or built-in support from your hosting platform or load balancer
          — issuing from Let&apos;s Encrypt, ZeroSSL, Google Trust Services or Buypass. Once renewal
          is automated, a shorter maximum lifetime stops being something to plan around.
        </p>

        <h2>See where you stand</h2>
        <p>
          SUN-DRAM Scanner reads a certificate&apos;s actual lifetime and issuer, and gives a direct
          verdict — automated, possibly automated, or manual — on whether a hostname is already
          ready for this change. See the{" "}
          <Link href="/countdown">full countdown and all three phase dates</Link>, or scan a
          hostname below.
        </p>
      </article>

      <GuideCta heading="Is this hostname ready for 2027?" />
    </main>
  );
}
