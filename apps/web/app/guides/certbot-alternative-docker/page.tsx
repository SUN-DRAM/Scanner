import type { Metadata } from "next";

import { GuideCta } from "@/components/scan/GuideCta";

export const metadata: Metadata = {
  title: "Certbot alternatives for Docker — automated TLS without the sidecar",
  description:
    "Running Certbot inside Docker Compose has real friction. Here are the alternatives that avoid it, and how to check any of them actually worked.",
};

export default function CertbotAlternativeDockerGuide() {
  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="text-sm font-medium text-cobalt">Guide</p>
      <h1 className="mt-2 font-display text-xl leading-display text-ink sm:text-2xl md:text-3xl">
        Certbot alternatives for Docker Compose
      </h1>
      <p className="mt-4 text-ink-muted">
        Certbot works. Running it well inside a container stack is the part that tends to go wrong.
      </p>

      <article className="prose-content mt-10 leading-prose text-ink">
        <h2>Where Certbot in Docker gets painful</h2>
        <p>
          The usual setup is a dedicated Certbot container, a shared volume for certificates, a cron
          job or systemd timer to trigger renewal, and a hook to reload whichever container is
          actually serving traffic once a new certificate lands. Every piece of that is a place
          things quietly break: the reload hook stops firing after a compose file change, the volume
          mount path drifts between environments, or the renewal container itself stops running and
          nobody notices until a certificate expires.
        </p>

        <h2>Alternatives that avoid the sidecar</h2>
        <p>
          <strong>Caddy</strong> issues and renews certificates automatically as part of serving
          traffic — no separate container, no cron job, no reload hook, because the same process
          doing the serving is the one managing the certificate.
        </p>
        <p>
          <strong>Traefik</strong> does the same as a reverse proxy in front of other containers,
          with ACME configuration living in the same place as routing rules — useful if you already
          want a reverse proxy layer rather than exposing nginx directly.
        </p>
        <p>
          <strong>acme.sh</strong> is a lighter-weight shell-script alternative to Certbot itself —
          smaller footprint, no Python dependency, and it supports the same ACME providers. It still
          needs the same renewal-and-reload wiring Certbot does, so it doesn&apos;t remove the
          sidecar problem on its own.
        </p>
        <p>
          <strong>A managed load balancer</strong> (a cloud provider&apos;s ALB, or a platform like
          Fly.io, Render or Railway) can take certificate management out of the container stack
          entirely, terminating TLS before traffic ever reaches your containers.
        </p>

        <h2>Whichever you use, verify it independently</h2>
        <p>
          Every one of these tools can fail silently in the same way Certbot can — a renewal that
          stops running, a reload that doesn&apos;t happen, a chain that&apos;s served incomplete.
          SUN-DRAM Scanner doesn&apos;t issue or renew certificates — it reads what a hostname is
          actually presenting right now, regardless of which tool put it there, and tells you
          plainly whether it&apos;s something to worry about.
        </p>
      </article>

      <GuideCta heading="Check what your setup is actually serving" />
    </main>
  );
}
