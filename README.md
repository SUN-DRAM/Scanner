# SUN-DRAM Scanner

Free public TLS/DNS scanner. Enter a hostname, get a graded report, share the link.

## Setup

1. `cp .env.example .env` (PowerShell: `Copy-Item .env.example .env`)
2. `docker compose up --build`
3. Wait for `api`, `web`, `postgres`, `redis` to report healthy.
4. Apply migrations: `docker compose exec api alembic upgrade head`
5. Open http://localhost:3000
6. Check API health: http://localhost:8000/api/v1/health

## Tests

```powershell
docker compose exec api pytest
docker compose exec api ruff check .
docker compose exec api mypy app
docker compose exec web pnpm lint
```

See `CONTRACT.md` for the binding engineering contract and `ROADMAP.md` for phase scope.
