# Deploy runbook — sundram.tech on DigitalOcean

Gate C (`docs/PHASE_1_GATE.md`). Written to be followed step by step, in order, at 2am if needed. Every command below runs **on the droplet** over SSH unless marked "local machine".

**Target:** DigitalOcean, Bangalore region (`blr1`), Ubuntu 24.04 LTS, 4GB RAM / 2 vCPU (`s-2vcpu-4gb`). Not a serverless platform — the scanner holds long TLS handshakes and background workers, the wrong shape for one (`docs/PHASE_1_GATE.md`).

**Architecture:** one droplet, Docker Compose (`docker-compose.prod.yml`), six containers: `caddy` (the only one with published ports) → `web` / `api` → `postgres` / `redis`, plus a local `unbound` DNS resolver in front of Cloudflare/Google. Nightly backups to DigitalOcean Spaces. See `docker-compose.prod.yml`'s own header comment for exactly how it differs from the dev compose file.

---

## 0. Prerequisites

**Local machine** (your laptop, not the droplet):
- A DigitalOcean account with billing set up.
- `ssh` and `git` available.
- A domain registrar account for `sundram.tech` where you can edit DNS records (or DigitalOcean's own DNS if you delegate nameservers there — this runbook assumes you manage the A/CAA records wherever they currently live).
- (Optional, for Sentry) A Sentry account and a project each for the api and web apps.

**Have ready before you start:**
- A strong Postgres password: `openssl rand -hex 24`
- A strong admin token: `openssl rand -hex 32`
- A real contact email for Let's Encrypt (not a placeholder — `example.com` addresses are rejected outright, confirmed while building this).
- DigitalOcean Spaces access keys, scoped to one bucket (create the bucket first — step 1.5 below).

---

## 1. Provision

### 1.1 Create the droplet

DigitalOcean control panel → Create → Droplets:
- **Region:** Bangalore (BLR1) — lowest latency to the product's primary market and closest to how search will see it.
- **Image:** Ubuntu 24.04 (LTS) x64.
- **Size:** Basic, Regular, `s-2vcpu-4gb` (4GB RAM / 2 vCPU, ~₹1,500–2,500/month per the phase gate's own estimate).
- **Authentication:** SSH key (upload your public key here — do not use a password).
- **Hostname:** something identifiable, e.g. `sundram-prod-blr1`.

Note the droplet's public IPv4 address once it's up — every step below refers to it as `$DROPLET_IP`.

### 1.2 First login and a non-root user

```bash
ssh root@$DROPLET_IP

adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# From here on, log in as deploy, not root:
exit
ssh deploy@$DROPLET_IP
```

### 1.3 Firewall

Only SSH, HTTP, and HTTPS are ever needed from the public internet — Postgres/Redis/Unbound are internal-only in `docker-compose.prod.yml` and never published.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp   # HTTP/3
sudo ufw enable
```

### 1.4 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
newgrp docker   # or log out and back in

docker --version
docker compose version
```

### 1.5 Create the DigitalOcean Spaces bucket

Control panel → Spaces → Create a Space, region **BLR1**, name it (e.g. `sun-dram-scanner-backups`). Then API → Spaces Keys → Generate New Key, scoped if possible to just this bucket. Save the access key ID and secret — they go in `.env` in step 3.2 and nowhere else.

### 1.6 Swap (recommended)

4GB is enough for this stack (see `docker-compose.prod.yml`'s per-service resource limits, which total well under 4GB), but a small swap file is a cheap insurance policy against an unexpected spike taking down the whole box instead of just slowing it down:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 2. DNS

At your registrar (or wherever `sundram.tech`'s nameservers point):

| Type | Name | Value |
|---|---|---|
| A | `sundram.tech` | `$DROPLET_IP` |
| A | `www.sundram.tech` | `$DROPLET_IP` |
| CAA | `sundram.tech` | `0 issue "letsencrypt.org"` |

The CAA record matters for the credibility check in step 8 — Caddy is configured to use Let's Encrypt specifically (`deploy/caddy/Caddyfile`), so this CAA record should name that CA, not be absent.

**Wait for propagation before continuing** — `dig sundram.tech +short` from your local machine should return `$DROPLET_IP`. This can take minutes to a few hours depending on the registrar and previous TTLs. Caddy will retry ACME issuance on its own (every ~60s, capped at 30 days per attempt) if you start the stack before this finishes, so it's safe to proceed once you're reasonably confident, but the site won't have a valid certificate until DNS is live.

---

## 3. First deploy

### 3.1 Clone the repo

```bash
sudo mkdir -p /opt/sun-dram-scanner
sudo chown deploy:deploy /opt/sun-dram-scanner
git clone <your-repo-url> /opt/sun-dram-scanner
cd /opt/sun-dram-scanner
```

### 3.2 Configure the environment

```bash
cp .env.production.example .env
chmod 600 .env
nano .env   # or vim — fill in every CHANGE_ME value
```

Every variable is documented inline in `.env.production.example`. At minimum you must set: `ADMIN_TOKEN`, `POSTGRES_PASSWORD`, `CADDY_EMAIL`, `DO_SPACES_BUCKET`, `DO_SPACES_ACCESS_KEY_ID`, `DO_SPACES_SECRET_ACCESS_KEY`. `SENTRY_DSN`/`NEXT_PUBLIC_SENTRY_DSN` can stay empty for now and be added later (step 7) without redeploying anything else.

### 3.3 Build and start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

First build takes several minutes (compiling the api's dependencies, building the web standalone bundle). Watch it come up:

```bash
docker compose -f docker-compose.prod.yml ps
```

Every service should reach `healthy` except `worker` (its healthcheck is deliberately disabled — see `docker-compose.prod.yml`'s comment on why: it runs `arq`, not an HTTP server, so there's nothing for an HTTP healthcheck to hit) and `caddy` (no built-in healthcheck; check its logs instead, next step).

### 3.4 Run migrations

**Not automatic** — a deliberate, single, explicit step, run once per deploy that changes the schema (most redeploys won't need this at all):

```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

### 3.5 Verify

```bash
# Internal health check (bypasses Caddy/DNS — proves the app itself is fine):
docker compose -f docker-compose.prod.yml exec api curl -s http://localhost:8000/api/v1/health

# Once DNS has propagated and Caddy has obtained a certificate:
curl -s https://sundram.tech/api/v1/health
curl -sI https://sundram.tech/ | head -20
```

Watch Caddy actually get a certificate:

```bash
docker compose -f docker-compose.prod.yml logs caddy --tail 50
```

Look for `"msg":"certificate obtained successfully"`. If you instead see `invalidContact` or similar, `CADDY_EMAIL` is a placeholder domain Let's Encrypt rejects — fix it in `.env` and run `docker compose -f docker-compose.prod.yml up -d caddy` to pick up the change.

### 3.6 Set up nightly backups

```bash
crontab -e
```

Add:

```
0 2 * * * cd /opt/sun-dram-scanner && ./scripts/backup.sh >> /var/log/scanner-backup.log 2>&1
```

02:00 server time (UTC, since the droplet's system clock is UTC by default and this stack doesn't change that) — outside India business hours, comfortably before anyone's first scan of the day.

Run it once by hand now to confirm it works before trusting cron with it:

```bash
sudo touch /var/log/scanner-backup.log
sudo chown deploy:deploy /var/log/scanner-backup.log
./scripts/backup.sh
```

---

## 4. Redeploy (routine updates)

```bash
cd /opt/sun-dram-scanner
git pull
docker compose -f docker-compose.prod.yml up -d --build

# Only if this deploy includes a migration:
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

`docker compose up -d --build` recreates only the containers whose image actually changed, so a frontend-only change doesn't restart the API mid-scan and vice versa. There is a brief gap (a few seconds) where a container being replaced is unavailable — for this product's traffic level, a documented `restart: unless-stopped` blip is an acceptable tradeoff against the complexity of a blue/green setup on a single droplet; revisit if traffic ever justifies it.

---

## 5. Rollback

If a deploy is bad, roll back to the last known-good commit and rebuild from it — the images are always built fresh from source (`docker-compose.prod.yml` has no bind mounts of source to fall out of sync), so this is the entire rollback:

```bash
cd /opt/sun-dram-scanner
git log --oneline -10          # find the last good commit
git checkout <good-commit-sha>
docker compose -f docker-compose.prod.yml up -d --build
```

If the bad deploy included a migration that also needs reverting:

```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
```

Then return to the latest commit once the fix is ready: `git checkout main`.

If the database itself is corrupted (not just the code), restore from backup instead — section 6.

---

## 6. Restore from backup

`scripts/restore.sh` has two modes. **Always try scratch mode first**, even during a real incident — it takes under a minute and proves the backup you're about to trust is actually restorable before you touch the live database.

### 6.1 Verify a backup restores cleanly (scratch — safe, non-destructive)

```bash
./scripts/restore.sh                 # latest backup
./scripts/restore.sh scanner-20260811-020000.sql.gz   # a specific one
```

This downloads the dump, loads it into a throwaway `postgres:16-alpine` container on `localhost:55432`, and prints row counts for `scans`/`waitlist_signups`/`daily_stats` so you can eyeball that the data looks right. The scratch container is left running afterward for further inspection (`psql -h localhost -p 55432 -U scanner -d scanner`, password `scratch`); remove it with `docker rm -f scanner-restore-scratch` when done.

### 6.2 Restore into production (destructive — disaster recovery only)

```bash
./scripts/restore.sh latest --target=prod
```

This stops `api` and `worker` (so nothing writes mid-restore), replaces every row in the live database, then restarts them. It requires typing `yes-overwrite-production` to proceed — there is no `--yes`/non-interactive flag, deliberately, since this is not an operation that should ever run unattended or inside another script by accident.

After it completes:

```bash
curl -s https://sundram.tech/api/v1/health
```

---

## 7. Error tracking (Sentry)

Optional, but Gate C requires it before calling the site production-ready — a bug is invisible until a customer complains without it.

1. Create two Sentry projects (or one, with separate environments — either works): one Python/FastAPI, one Next.js.
2. Set `SENTRY_DSN` in `.env` to the api project's DSN.
3. Set `NEXT_PUBLIC_SENTRY_DSN` in `.env` to the web project's DSN. (This value gets baked into the client bundle at build time — see `apps/web/Dockerfile.prod` — so it needs a rebuild, not just a restart, to take effect.)
4. Optionally, for readable stack traces in Sentry instead of minified ones: set `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` too (source-map upload at build time; the build succeeds without them regardless).
5. Redeploy:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Confirm it's wired up by checking the Sentry project for an event after intentionally triggering one (e.g. temporarily point `DATABASE_URL` at a bad host and hit `/api/v1/health`, then revert) — or just wait for the first real error, since Sentry's own dashboard will show "no events yet" clearly either way.

---

## 8. Uptime monitoring

External to the droplet, deliberately — if the droplet itself goes down, nothing running on it can page you about that.

1. Pick a free-tier service (UptimeRobot, Better Uptime, Pingdom's free tier, or similar — any HTTP monitor works, this isn't prescriptive).
2. Monitor: `GET https://sundram.tech/api/v1/health`, expecting HTTP 200 and, if the tool supports body matching, the substring `"status": "ok"` (contract §7's health endpoint — `degraded` is still a 200, since db/redis being individually down is a real but non-fatal state worth distinguishing from "unreachable").
3. Interval: 1–5 minutes.
4. Alert channel: SMS or a phone push notification, not just email — per the phase gate's explicit ask ("alerting to my phone").

---

## 9. The credibility check

**Do this after every one of the steps above, not just once.** A certificate-readiness product whose own site scores anything less than A+ is the single most avoidable credibility failure available to this product (`docs/PHASE_1_GATE.md`).

```bash
curl -s -X POST https://sundram.tech/api/v1/scans -H 'Content-Type: application/json' -d '{"hostname":"sundram.tech"}'
# poll the returned poll_url, or just open the share_url in a browser
```

Or simplest: open `https://sundram.tech`, scan `sundram.tech` through the product's own UI.

**Must be A+.** If it isn't, the specific things this product itself checks are exactly the things to fix first, in order of what's cheapest to have missed:
- **HSTS long max-age** — already set to one year in `deploy/caddy/Caddyfile`; if missing, confirm Caddy actually reloaded that config.
- **CAA record** — set in step 2; if `DNS_NO_CAA` fires, it hasn't propagated yet or wasn't added.
- **TLS 1.3 / complete chain** — Caddy's automatic HTTPS handles both by default; a failure here almost always means an old cached certificate from before a Caddyfile change. Check `docker compose -f docker-compose.prod.yml logs caddy` for the actual issuer chain served.
- **CSP** — set in the Caddyfile; if the finding fires, confirm the header is actually reaching the client (`curl -sI https://sundram.tech/`), not just present in the Caddyfile.

Then, **on a real phone on mobile data** (not a desktop browser resized to 360px) — this is the actual distribution mechanism, someone pasting a share link into a WhatsApp group:
1. Run a scan from the phone's browser.
2. Confirm the share link loads and reads correctly.
3. Confirm the grade dial, validity bar, and finding list are all legible and don't overflow at real mobile width.

---

## Troubleshooting

**Every server-rendered page 500s with a fetch/connect timeout to `sundram.tech`.** This was a real bug found while building this runbook, now fixed (`apps/web/lib/api.ts`): server-side rendering runs inside the `web` container, which must reach `api` directly over the internal Docker network (`http://api:8000`), never through the public domain — many cloud providers, DigitalOcean droplets included, don't support "hairpin" routing back to their own public IP from inside themselves, so a self-fetch through the public domain can fail even with correct DNS. If you see this, you're likely running an older build; `git pull` and redeploy.

**`relation "scans" does not exist"` on the first scan after a fresh deploy.** Migrations weren't run — see step 3.4. They are deliberately not automatic (so a bad migration can't silently run itself on every redeploy); this is the one step it's easiest to forget on a brand new droplet specifically.

**Caddy keeps logging `will retry` for certificate issuance.** Almost always DNS hasn't propagated yet (step 2) — `dig sundram.tech +short` should return the droplet's IP from outside the droplet itself before Caddy can succeed. Also check `CADDY_EMAIL` isn't a placeholder domain (Let's Encrypt rejects those outright, not just slowly).

**`worker` shows no health status / `unhealthy` right after `docker compose ps`.** Its healthcheck is intentionally disabled (`docker-compose.prod.yml` — the image's baked-in HTTP healthcheck targets uvicorn's port, but this service runs `arq`, which listens on nothing). Check it's actually processing jobs instead: `docker compose -f docker-compose.prod.yml logs worker --tail 50`.
