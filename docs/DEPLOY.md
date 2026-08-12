# Deploy runbook — sundram.tech on AWS EC2

Written to be followed step by step, in order, at 2am if needed. Every command below runs **on the instance** over SSH unless marked "local machine".

**Target:** AWS EC2, Mumbai region (`ap-south-1`), Ubuntu, `t3.medium` (2 vCPU / 4GB RAM). Not a serverless platform — the scanner holds long TLS handshakes and background workers, the wrong shape for one.

**Architecture:** one instance, Docker Compose (`docker-compose.prod.yml`), six containers: `caddy` (the only one with published ports) → `web` / `api` → `postgres` / `redis`, plus a local `unbound` DNS resolver in front of Cloudflare/Google. Nightly backups to S3 (`ap-south-1`) via an IAM role attached to the instance. See `docker-compose.prod.yml`'s own header comment for exactly how it differs from the dev compose file.

**Facts about the current instance** (not guesses — confirmed live):
- Public IPv4: `65.2.195.179` — Elastic IP, permanently allocated and associated. Survives stop/start. This is the value everything below refers to as `$INSTANCE_IP`.
- Internal hostname: `ip-172-31-0-62` (default VPC, `172.31.0.0/16`)
- OS user: `ubuntu`
- Deploy directory: `/opt/scanner` (not `/opt/sun-dram-scanner` — an earlier draft of this runbook used that path; the actual instance was provisioned with the shorter one and that's what's real)
- Domain: `sundram.tech`, apex and `www`, registered at Spaceship, nameservers `launch1.spaceship.net.` / `launch2.spaceship.net.`

---

## 0. Prerequisites

**Local machine** (your laptop, not the instance):
- An AWS account with billing set up.
- `ssh` and `git` available.
- The EC2 key pair's private key (`.pem` file) for this instance.
- Access to `sundram.tech`'s DNS at Spaceship (or wherever the domain is delegated) to edit A/CAA/TXT records.
- (Optional, for Sentry) A Sentry account and a project each for the api and web apps.

**Have ready before you start:**
- A strong Postgres password: `openssl rand -hex 24`
- A strong admin token: `openssl rand -hex 32`
- A real contact email for Let's Encrypt (not a placeholder — `example.com` addresses are rejected outright).
- An S3 bucket in `ap-south-1` for backups, and an IAM role attached to the instance scoped to read/write just that bucket (see 1.5).

---

## 1. Provision

### 1.1 Launch the instance

EC2 console → Launch instance:
- **Region:** Asia Pacific (Mumbai) `ap-south-1` — lowest latency to the product's primary market.
- **AMI:** Ubuntu, latest LTS, x86_64.
- **Instance type:** `t3.medium` (2 vCPU / 4GB RAM).
- **Key pair:** create or select one, download the `.pem` — this is the only credential that gets you in. There is no password login.
- **Network:** default VPC (`172.31.0.0/16`) is fine.
- **Security group:** inbound `22` (restrict to your own IP, not `0.0.0.0/0`), `80` and `443` from anywhere, nothing else. Postgres (`5432`) and Redis (`6379`) are never published to the host by `docker-compose.prod.yml`, so there is nothing to open for them — confirm this from outside the instance after first deploy (step 3.5).
- **Storage:** default gp3 volume is fine for this workload.

### 1.2 Allocate and associate an Elastic IP

Do this immediately, before anything else depends on the instance's address — a plain public IPv4 changes on stop/start and breaks DNS every time. EC2 console → Elastic IPs → Allocate → Associate with this instance. Record the address; every step below calls it `$INSTANCE_IP`. **Releasing the Elastic IP while it's detached is the one action that breaks DNS again** — never do this without immediately updating the DNS A records to match.

### 1.3 First login and a non-root user

```bash
ssh -i your-key.pem ubuntu@$INSTANCE_IP
```

Ubuntu AMIs already provide a non-root `ubuntu` user with passwordless sudo — there is no separate root-login/adduser step the way there would be on a fresh DigitalOcean droplet.

### 1.4 Firewall

Security Groups, not `ufw`, are the firewall here — they filter at the AWS network layer before traffic ever reaches the instance, so `ufw` is left inactive deliberately (an active-but-redundant host firewall is one more thing that can silently drift from the security group and cause a confusing outage). Confirm the security group attached to the instance allows only:

| Port | Source |
|---|---|
| 22 | your IP only |
| 80 | `0.0.0.0/0` |
| 443 (tcp + udp, for HTTP/3) | `0.0.0.0/0` |

Everything else closed. Verify from outside the instance that nothing else is reachable:

```bash
# from your local machine
nc -zv -w5 $INSTANCE_IP 5432   # should fail/timeout
nc -zv -w5 $INSTANCE_IP 6379   # should fail/timeout
```

An open 5432 or 6379 here is a live incident, not a documentation gap — fix the security group immediately.

### 1.5 IAM role for backups

Create an IAM policy scoped to just the backup bucket (`GetObject`/`PutObject`/`ListBucket`/`DeleteObject` on `arn:aws:s3:::sun-dram-scanner-backups` and `arn:aws:s3:::sun-dram-scanner-backups/*`), create a role with that policy, and attach the role to the instance (EC2 console → instance → Actions → Security → Modify IAM role). `aws-cli` on the instance picks up credentials from this role automatically via the instance metadata service — no access key ever needs to exist on disk. Create the bucket itself first, in `ap-south-1`.

### 1.6 Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker   # or log out and back in

docker --version
docker compose version
```

### 1.7 Swap

`t3.medium` gives 4GB RAM for six containers plus concurrent scans — tight enough that a burst (a scheduled re-scan backlog colliding with a spike of public scans, once Phase 2's scheduler exists) can OOM-kill the worker silently, which for an alerting product is the worst failure mode available: the customer hears nothing and assumes all is well. A swap file is cheap insurance:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # confirm swap shows 2.0Gi
```

---

## 2. DNS

At Spaceship (or wherever `sundram.tech`'s nameservers point):

| Type | Name | Value |
|---|---|---|
| A | `sundram.tech` | `$INSTANCE_IP` |
| A | `www.sundram.tech` | `$INSTANCE_IP` |
| CAA | `sundram.tech` | `0 issue "letsencrypt.org"` |
| TXT | `sundram.tech` | an SPF record for whatever actually sends mail as this domain, e.g. `v=spf1 include:_spf.google.com ~all` |
| TXT | `_dmarc.sundram.tech` | `v=DMARC1; p=none; rua=mailto:you@sundram.tech` (start at `p=none` to monitor before enforcing) |

The CAA record matters for the credibility check in step 9 — Caddy is configured to use Let's Encrypt specifically (`deploy/caddy/Caddyfile`), so this CAA record should name that CA, not be absent. SPF/DMARC (and DKIM, configured wherever the sending mail provider documents it) matter for the `email_auth` module's own grade on our own domain, and because Phase 2's alert emails are worthless if they land in spam.

**Wait for propagation before continuing** — `dig sundram.tech +short` from your local machine should return `$INSTANCE_IP`. Caddy will retry ACME issuance on its own if you start the stack before this finishes, so it's safe to proceed once you're reasonably confident, but the site won't have a valid certificate until DNS is live.

---

## 3. First deploy

### 3.1 Clone the repo

```bash
sudo mkdir -p /opt/scanner
sudo chown ubuntu:ubuntu /opt/scanner
git clone <your-repo-url> /opt/scanner
cd /opt/scanner
```

### 3.2 Configure the environment

```bash
cp .env.production.example .env
chmod 600 .env
nano .env   # or vim — fill in every CHANGE_ME value
```

Every variable is documented inline in `.env.production.example`. At minimum: `ADMIN_TOKEN`, `POSTGRES_PASSWORD` (a real generated secret — not a placeholder string; if you're inheriting an instance where this was ever set to something guessable, rotate it: `docker compose -f docker-compose.prod.yml exec postgres psql -U scanner -d scanner -c "ALTER USER scanner WITH PASSWORD '<new>';"`, then update `.env` and restart `api`/`worker`), `APP_ENV=production`, `CORS_ORIGINS`, `PUBLIC_BASE_URL`, `CADDY_EMAIL`, `S3_BACKUP_BUCKET`. `SENTRY_DSN`/`NEXT_PUBLIC_SENTRY_DSN` can stay empty for now (step 7).

`PUBLIC_BASE_URL` and `NEXT_PUBLIC_SITE_URL` must both be `https://sundram.tech` — if either is left on its `localhost` default, share links (`share_url` in every scan response) come back pointing at `localhost`, silently breaking the product's entire distribution mechanism (a shared scan link in a WhatsApp group). This has happened before; check it explicitly after every deploy:

```bash
curl -s -X POST https://sundram.tech/api/v1/scans -H 'Content-Type: application/json' -d '{"hostname":"example.com"}' | grep -o '"share_url":"[^"]*"'
# must start with "share_url":"https://sundram.tech/
```

### 3.3 Build and start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Watch it come up:

```bash
docker compose -f docker-compose.prod.yml ps
```

Every service should reach `healthy` except `worker` (healthcheck deliberately disabled — it runs `arq`, not an HTTP server) and `caddy` (no built-in healthcheck; check its logs instead, next step).

### 3.4 Run migrations

**Not automatic** — a deliberate, single, explicit step, run once per deploy that changes the schema:

```bash
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Skipping this is the single easiest mistake on a fresh instance — the API and health check both come up looking fine, but every scan request fails with `relation "scans" does not exist` because the schema was never created. `alembic current` returning nothing is the tell; `alembic upgrade head` is idempotent, safe to run again if unsure.

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
0 2 * * * cd /opt/scanner && ./scripts/backup.sh >> /var/log/scanner-backup.log 2>&1
```

02:00 UTC (the instance's system clock is UTC by default) — outside India business hours, comfortably before anyone's first scan of the day.

Run it once by hand now to confirm it works before trusting cron with it:

```bash
sudo touch /var/log/scanner-backup.log
sudo chown ubuntu:ubuntu /var/log/scanner-backup.log
./scripts/backup.sh
```

This requires the IAM role from step 1.5 to already be attached — if it errors on the `aws s3 cp`, check `aws sts get-caller-identity` returns something (confirms the role is attached and readable) before suspecting anything else.

### 3.7 EBS snapshots (second backup layer)

S3 backups (above) protect the data; EBS snapshots protect against a corrupted or unbootable volume. EC2 console → the instance's root volume → Actions → Create snapshot, or automate with Data Lifecycle Manager: a daily snapshot, retained 7 days, is enough for a single-instance deployment at this stage.

---

## 4. Redeploy (routine updates)

```bash
cd /opt/scanner
git pull
docker compose -f docker-compose.prod.yml up -d --build

# Only if this deploy includes a migration:
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

`docker compose up -d --build` recreates only the containers whose image actually changed. There is a brief gap (a few seconds) where a container being replaced is unavailable — for this product's traffic level, a documented `restart: unless-stopped` blip is an acceptable tradeoff against the complexity of a blue/green setup on a single instance; revisit if traffic ever justifies it.

---

## 5. Rollback

```bash
cd /opt/scanner
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

This downloads the dump from S3, loads it into a throwaway `postgres:16-alpine` container on `localhost:55432`, and prints row counts for `scans`/`waitlist_signups`/`daily_stats`. The scratch container is left running afterward for further inspection (`psql -h localhost -p 55432 -U scanner -d scanner`, password `scratch`); remove it with `docker rm -f scanner-restore-scratch` when done.

### 6.2 Restore into production (destructive — disaster recovery only)

```bash
./scripts/restore.sh latest --target=prod
```

This stops `api` and `worker` (so nothing writes mid-restore), replaces every row in the live database, then restarts them. It requires typing `yes-overwrite-production` to proceed — there is no `--yes`/non-interactive flag, deliberately.

After it completes:

```bash
curl -s https://sundram.tech/api/v1/health
```

---

## 7. Error tracking (Sentry)

Optional, but recommended before calling the site production-ready — a bug is invisible until a customer complains without it.

1. Create two Sentry projects (or one, with separate environments): one Python/FastAPI, one Next.js.
2. Set `SENTRY_DSN` in `.env` to the api project's DSN.
3. Set `NEXT_PUBLIC_SENTRY_DSN` in `.env` to the web project's DSN. (Baked into the client bundle at build time — see `apps/web/Dockerfile.prod` — so it needs a rebuild, not just a restart.)
4. Optionally, for readable stack traces: set `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` (source-map upload at build time; the build succeeds without them regardless).
5. Redeploy: `docker compose -f docker-compose.prod.yml up -d --build`

---

## 8. Uptime monitoring

External to the instance, deliberately — if the instance itself goes down, nothing running on it can page you about that.

1. Pick a free-tier service (UptimeRobot, Better Uptime, Pingdom's free tier, or similar).
2. Monitor: `GET https://sundram.tech/api/v1/health`, expecting HTTP 200 and, if the tool supports body matching, the substring `"status": "ok"` (`degraded` is still a 200 — db/redis being individually down is real but non-fatal, worth distinguishing from "unreachable").
3. Interval: 1–5 minutes.
4. Alert channel: SMS or a phone push notification, not just email.

---

## 9. The credibility check

**Do this after every one of the steps above, not just once.** A certificate-readiness product whose own site scores anything less than A+ is the single most avoidable credibility failure available to this product.

```bash
curl -s -X POST https://sundram.tech/api/v1/scans -H 'Content-Type: application/json' -d '{"hostname":"sundram.tech"}'
# poll the returned poll_url, or just open the share_url in a browser
```

Or simplest: open `https://sundram.tech`, scan `sundram.tech` through the product's own UI. This is expected to work and return our own real grade — the SSRF guard (`apps/api/app/safety.py`) only blocks our raw server IP (`65.2.195.179`) submitted literally, never the hostname itself; see the comment on `OWN_PUBLIC_IPS` there for why.

**Must be A+.** If it isn't:
- **HSTS long max-age** — already set to one year in `deploy/caddy/Caddyfile`; if missing, confirm Caddy actually reloaded that config.
- **CAA record** — set in step 2; if `DNS_NO_CAA` fires, it hasn't propagated yet or wasn't added.
- **TLS 1.3 / complete chain** — Caddy's automatic HTTPS handles both by default; a failure here almost always means an old cached certificate from before a Caddyfile change.
- **CSP** — set in the Caddyfile; if the finding fires, confirm the header is actually reaching the client (`curl -sI https://sundram.tech/`), not just present in the Caddyfile.
- **SPF/DMARC/DKIM** — set at the registrar (step 2) and with your email provider; the `email_auth` module grades these independently of the TLS-related checks above.

Then, **on a real phone on mobile data** (not a desktop browser resized to 360px):
1. Run a scan from the phone's browser.
2. Confirm the share link loads and reads correctly.
3. Confirm the grade dial, validity bar, and finding list are all legible and don't overflow at real mobile width.

---

## Troubleshooting

**Every server-rendered page 500s with a fetch/connect timeout to `sundram.tech`.** Server-side rendering runs inside the `web` container, which must reach `api` directly over the internal Docker network (`http://api:8000`), never through the public domain — many cloud providers, EC2 included, don't support "hairpin" routing back to their own public IP from inside themselves. If you see this, check `apps/web/lib/api.ts` uses the internal URL for server-side fetches.

**`relation "scans" does not exist"` on the first scan after a fresh deploy, or after an instance stop/start.** Migrations weren't run — see step 3.4. They are deliberately not automatic (so a bad migration can't silently run itself on every redeploy); this is the one step it's easiest to forget, and a stopped/restarted instance that comes back "healthy" (the health check only proves DB *connectivity*, not schema) can mask it for a while.

**`share_url` in a scan response starts with `http://localhost:3000`.** `PUBLIC_BASE_URL` isn't set to `https://sundram.tech` in `.env` — see step 3.2. Every previously-generated share link with this problem is already broken and unrecoverable; the fix only prevents new ones.

**Caddy keeps logging `will retry` for certificate issuance.** Almost always DNS hasn't propagated yet (step 2) — `dig sundram.tech +short` should return `$INSTANCE_IP` from outside the instance itself before Caddy can succeed. Also check `CADDY_EMAIL` isn't a placeholder domain.

**`worker` shows no health status / `unhealthy` right after `docker compose ps`.** Its healthcheck is intentionally disabled — the image's baked-in HTTP healthcheck targets uvicorn's port, but this service runs `arq`, which listens on nothing. Check it's actually processing jobs: `docker compose -f docker-compose.prod.yml logs worker --tail 50`.

**Instance was stopped and restarted (e.g. to attach/detach something) and the Elastic IP still resolves correctly, but nothing else looks right.** A stop/start recreates nothing about the Docker state — containers restart automatically (`restart: unless-stopped`) and should come back exactly as they were, migrations included. If something seems freshly broken after a restart that wasn't before, suspect `.env` drift (was it edited since the last known-good state?) rather than the restart itself.
