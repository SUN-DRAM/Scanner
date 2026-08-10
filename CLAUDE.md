# SUN-DRAM Scanner

Public TLS/DNS scanner. A stranger enters a hostname and gets a graded report they can share. Built for non-specialist founders and agencies in India facing the CA/Browser Forum certificate lifetime cuts (200 days now, 100 days from 15 March 2027).

## Read this first

`CONTRACT.md` at the repo root is the binding engineering contract. Read it in full before writing code in any area you haven't touched yet. It defines every enum, field name, endpoint, error code, finding code, grading rule, and design token.

`ROADMAP.md` defines phase scope. We are in **Phase 1**. Building anything from Phase 2+ is scope creep — say so and stop.

## Non-negotiable rules

1. **The contract wins.** If what you're about to write contradicts `CONTRACT.md`, stop and reply `CONTRACT GAP: <problem>`. Never invent a field name, enum value, error code, or endpoint.
2. **JSON is `snake_case` everywhere.** No camelCase conversion layer, no Pydantic aliases. `days_until_expiry` is spelled identically in Python, in JSON, and in TSX.
3. **Backend computes, frontend renders.** All grades, scores, severities, verdicts, countdowns, and display sentences come from the API. The frontend never recalculates a grade or derives days-until-expiry from a timestamp.
4. **`apps/api/app/schemas.py` and `apps/web/types/contract.ts` change together, in the same edit.** Never one without the other.
5. **Complete files only.** No `# ... unchanged`, no `// rest of implementation`, no placeholder bodies, no "you can add this later".
6. **Timestamps are ISO 8601 UTC with `Z`.** Durations are int milliseconds suffixed `_ms`. Day counts are ints suffixed `_days`. Never naive datetimes, never local time.
7. **Accuracy over coverage.** A false "expiring in 3 days" on a healthy certificate permanently destroys trust and is worse than no product. Where a check is uncertain, return `null` and lower the confidence — never guess. This applies hardest to WHOIS.
8. **Safety is not optional.** Contract §10 (resolve-then-validate, private-range blocklist, IP-pinned connections, redirect revalidation, port allowlist, rate limits) is a hard requirement. This service takes arbitrary hostnames from the public internet; built carelessly it is an SSRF engine.
9. **No secrets in code.** Config comes from the env vars in contract §4 only.
10. **Never store raw client IPs.** Hash them. DPDP hygiene starts now.

## Stack (locked — do not substitute)

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic · PostgreSQL 16 · Redis 7 · arq
Next.js 15 App Router · TypeScript · Tailwind v4 · shadcn/ui · pnpm

No Redux, no MUI, no Bootstrap, no Prisma, no Django, no additional state library. No `localStorage` or `sessionStorage` anywhere.

## Commands

```powershell
docker compose up --build          # full stack
docker compose exec api pytest     # backend tests
docker compose exec api ruff check .
docker compose exec api mypy app
docker compose exec api alembic upgrade head
docker compose exec web pnpm lint
docker compose exec web pnpm build
```

Health check: `http://localhost:8000/api/v1/health` must return `200` with database and redis both `ok`.

## Environment

Windows host, repo at `D:\Scanner`, Docker Desktop. Give PowerShell commands, not bash. Watch line endings and volume mount paths.

## Working agreement

- Build in the order the phase prompt specifies. At the end of each step, stop, list the files produced with full paths, and wait for confirmation before continuing.
- State assumptions out loud in one line before the code when the contract doesn't specify something.
- Run the relevant tests before declaring a step done.
- Write user-facing copy in sentence case, active voice. Errors state what happened and what to do, and never apologise. No "Oops", no exclamation marks.
