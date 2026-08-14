import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Guides",
  description: "Certificate lifetimes, renewal automation, and getting ready for March 2027.",
  alternates: { canonical: "/guides" },
};

const GUIDES = [
  {
    href: "/guides/100-day-certificate-2027",
    title: "The 100-day certificate rule, and what it actually means",
    description: "What's changing on 15 March 2027, why, and how to be ready.",
  },
  {
    href: "/guides/ssl-certificate-expiry-monitoring",
    title: "SSL certificate expiry monitoring, done properly",
    description: "Why manual tracking fails and what proper monitoring actually checks.",
  },
  {
    href: "/guides/nginx-auto-ssl-renewal",
    title: "Automatic SSL renewal for nginx",
    description: "A working Certbot setup, and the specific points where it breaks.",
  },
  {
    href: "/guides/certbot-alternative-docker",
    title: "Certbot alternatives for Docker Compose",
    description: "Avoiding the renewal-sidecar problem entirely.",
  },
  {
    href: "/guides/free-ssl-checker-india",
    title: "A free SSL checker built for Indian founders and agencies",
    description: "No signup, no cost, and DPDP-conscious by default.",
  },
] as const;

export default function GuidesIndexPage() {
  return (
    <main className="mx-auto max-w-content px-4 py-16">
      <h1 className="font-display text-2xl leading-display text-ink sm:text-3xl">Guides</h1>
      <p className="mt-3 max-w-reading text-ink-muted">
        Certificate lifetimes, renewal automation, and getting ready for the CA/Browser Forum&apos;s
        March 2027 change.
      </p>

      <ul className="mt-10 flex flex-col divide-y divide-line rounded-card border border-line bg-surface">
        {GUIDES.map((guide) => (
          <li key={guide.href}>
            <Link href={guide.href} className="block px-6 py-5 transition-colors hover:bg-paper">
              <p className="font-display text-lg leading-display text-ink">{guide.title}</p>
              <p className="mt-1 text-sm text-ink-muted">{guide.description}</p>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
