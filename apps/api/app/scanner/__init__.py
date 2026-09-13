"""Shared scaffolding for the seven scan modules: the one uniform signature
they all share, and the timeout/exception handling that belongs in exactly
one place rather than being re-implemented seven times.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from app.enums import ModuleErrorCode, ModuleName, ModuleStatus
from app.grading import grade_module, score_module, status_for_findings
from app.safety import PER_MODULE_TIMEOUT_SECONDS, classify_module_exception
from app.schemas import Finding, ModuleError, ModuleResult

logger = logging.getLogger("app.scanner")

DataT = TypeVar("DataT", bound=BaseModel)

# v3.4 (docs/Fix headers and incomplete.md): the user-facing message for
# every code except MODULE_TIMEOUT, which needs the module's own label and
# actual timeout value — built inline in run_module instead. Deliberately
# generic and safe: no hostname, no library name, no stack detail. The full
# exception always goes to the application log (below), never here.
_MODULE_ERROR_MESSAGES: dict[ModuleErrorCode, str] = {
    ModuleErrorCode.CONNECTION_REFUSED: "The connection was refused.",
    ModuleErrorCode.CONNECTION_RESET: "The connection was reset partway through.",
    ModuleErrorCode.TLS_ERROR: "The TLS connection could not be established.",
    ModuleErrorCode.TOO_MANY_REDIRECTS: "This check followed too many redirects.",
    ModuleErrorCode.BLOCKED_REDIRECT_TARGET: (
        "This check followed a redirect to a target it is not permitted to connect to."
    ),
    ModuleErrorCode.HTTP_ERROR: "The request could not be completed.",
    ModuleErrorCode.UNEXPECTED_ERROR: "This check did not complete. Try scanning again.",
}


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
        # v3.4: the full exception — type, message, traceback — is for the
        # application log only, correlated by module and hostname (this
        # runs in the arq worker, outside any HTTP request, so there is no
        # per-request request_id to attach here). ModuleResult.error below
        # carries only a closed code and a safe, generic message; nothing
        # from this log line ever reaches the API response.
        logger.exception(
            "module_failed",
            # "module" collides with LogRecord's own built-in attribute of
            # that name and raises inside the logging call itself — not a
            # hypothetical, this took the exception-logging path down with
            # it until a test actually exercised it.
            extra={"scan_module": module.value, "hostname": ctx.hostname, "port": ctx.port},
        )
        code = classify_module_exception(exc)
        if code == ModuleErrorCode.MODULE_TIMEOUT:
            message = f"The {label.lower()} check timed out after {timeout:g} seconds."
        else:
            message = _MODULE_ERROR_MESSAGES[code]
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
            error=ModuleError(code=code, message=message),
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
