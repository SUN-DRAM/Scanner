"""arq worker entrypoint (contract §3.2). Run via `arq app.worker.WorkerSettings`
(the `worker` service in docker-compose.yml).

The only job this queue ever processes is `run_scan_job`: run the full scan
for an already-`queued` `scans` row and persist the result. All status
transitions (`queued` -> `running` -> `completed`/`failed`) happen inside
`app.scanner.orchestrator.run_scan` itself — this function is a thin async
entrypoint that gives it a database session.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.config import get_settings
from app.db import get_sessionmaker
from app.scanner.orchestrator import run_scan


async def run_scan_job(_ctx: dict[str, Any], scan_id: str) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await run_scan(session, scan_id)


class WorkerSettings:
    functions = (run_scan_job,)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Comfortably above SCAN_TIMEOUT_SECONDS so the orchestrator's own
    # whole-scan budget (§10 rule 5) is always what actually cuts a stuck
    # scan short, not arq's job timeout racing it.
    job_timeout = get_settings().scan_timeout_seconds + 10
    max_jobs = 10
