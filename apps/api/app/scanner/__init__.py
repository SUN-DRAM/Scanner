"""Shared scaffolding for the seven scan modules: the one uniform signature
they all share, and the timeout/exception handling that belongs in exactly
one place rather than being re-implemented seven times.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from app.enums import ModuleName, ModuleStatus
from app.grading import grade_module, score_module, status_for_findings
from app.safety import PER_MODULE_TIMEOUT_SECONDS
from app.schemas import Finding, ModuleResult

DataT = TypeVar("DataT", bound=BaseModel)


@dataclass(frozen=True)
class ScanContext:
    """Everything a module needs, and nothing it has to compute for itself:
    the hostname/port to scan, and the single `now` the whole scan shares so
    every module's date arithmetic (days_until_expiry and so on) is
    reproducible against fixed test fixtures rather than reading the clock
    independently in seven places."""

    hostname: str
    port: int
    now: datetime


DetectFn = Callable[[ScanContext], Awaitable[tuple[DataT, list[Finding], str]]]


async def run_module(
    *,
    module: ModuleName,
    label: str,
    ctx: ScanContext,
    detect: DetectFn[DataT],
    timeout: float = PER_MODULE_TIMEOUT_SECONDS,
) -> ModuleResult[DataT]:
    """Runs `detect(ctx)` under an 8-second timeout, catching every exception
    into `status: "error"` rather than raising — a module never takes the
    whole scan down. `detect` returns `(data, findings, summary)`; score,
    grade and operational status are derived from `findings` via the shared
    grading helpers, never duplicated per module.
    """
    started = time.perf_counter()
    try:
        data, findings, summary = await asyncio.wait_for(detect(ctx), timeout=timeout)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ModuleResult(
            module=module,
            status=ModuleStatus.ERROR,
            score=None,
            grade=None,
            label=label,
            summary="This check did not complete — try scanning again.",
            checked_at=ctx.now,
            duration_ms=duration_ms,
            findings=[],
            data=None,
            error=str(exc) or exc.__class__.__name__,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    score = score_module(findings)
    return ModuleResult(
        module=module,
        status=status_for_findings(findings),
        score=score,
        grade=grade_module(score, findings),
        label=label,
        summary=summary,
        checked_at=ctx.now,
        duration_ms=duration_ms,
        findings=findings,
        data=data,
        error=None,
    )
