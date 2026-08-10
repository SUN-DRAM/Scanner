import type { Metadata } from "next";

import { GuideCta } from "@/components/scan/GuideCta";

export const metadata: Metadata = {
  title: "Automatic SSL renewal for nginx — a working setup",
  description:
    "A working nginx auto-renewal setup with Certbot, the failure points that actually cause outages, and how to confirm it's really working.",
};

export default function NginxAutoSslRenewalGuide() {
  return (
    <main className="mx-auto max-w-reading px-4 py-16">
      <p className="text-sm font-medium text-cobalt">Guide</p>
      <h1 className="mt-2 font-display text-xl leading-display text-ink sm:text-2xl md:text-3xl">
        Automatic SSL renewal for nginx
      </h1>
      <p className="mt-4 text-ink-muted">
        The standard nginx and Certbot setup is reliable once it&apos;s configured correctly — the
        failures almost always happen at one of a few specific points.
      </p>

      <article className="prose-content mt-10 leading-prose text-ink">
        <h2>A working baseline</h2>
        <p>
          Certbot&apos;s nginx plugin (<code>certbot --nginx</code>) issues the certificate, writes
          it to <code>/etc/letsencrypt/live/&lt;hostname&gt;/</code>, and edits the nginx config to
          point at it. Certbot installs a systemd timer (or cron job, on older installs) that runs{" "}
          <code>certbot renew</code> twice a day, which only actually renews certificates within 30
          days of expiry — so it&apos;s safe to run frequently.
        </p>

        <h2>Where it actually breaks</h2>
        <p>
          <strong>The HTTP-01 challenge gets blocked.</strong> Certbot&apos;s default validation
          method needs port 80 reachable from the public internet for the challenge request. A
          firewall change, a reverse proxy in front of nginx, or a redirect that sends
          <code> /.well-known/acme-challenge/</code> to HTTPS before Certbot can respond will all
          break renewal — quietly, since the current certificate keeps working right up until it
          expires.
        </p>
        <p>
          <strong>nginx never reloads.</strong> Certbot renewing the certificate files doesn&apos;t
          make nginx pick them up — nginx only reads the certificate at startup or reload. Without a{" "}
          <code>--deploy-hook</code> (or the equivalent in{" "}
          <code>/etc/letsencrypt/renewal-hooks/deploy/</code>) running <code>nginx -s reload</code>,
          the renewed certificate sits on disk while nginx keeps serving the old, soon-to-expire
          one.
        </p>
        <p>
          <strong>The renewal timer itself stops running.</strong> A server rebuild, an OS upgrade
          that resets systemd units, or a container restart that doesn&apos;t persist the timer can
          all leave nothing actually calling <code>certbot renew</code> anymore, with no error until
          the certificate is already gone.
        </p>

        <h2>Confirm it&apos;s actually working</h2>
        <p>
          The only way to know renewal is genuinely working — not just configured — is to check what
          the server is actually serving, independent of what the renewal tooling believes it did.
          That&apos;s a plain external scan, not a look at Certbot&apos;s own logs.
        </p>
      </article>

      <GuideCta heading="Confirm your nginx setup is actually renewing" />
    </main>
  );
}
