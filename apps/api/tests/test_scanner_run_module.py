"""Tests for `app/scanner/__init__.py`'s `run_module` — the one place every
module's exception handling lives (contract §6.2 `ModuleResult.error`,
docs/Fix headers and incomplete.md Step 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

import pytest
from pydantic import BaseModel

from app.enums import ModuleErrorCode, ModuleName, ModuleStatus
from app.scanner import ScanContext, run_module
from app.schemas import ModuleResult


def _ctx() -> ScanContext:
    return ScanContext(hostname="example.com", port=443, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_a_timeout_produces_a_message_naming_the_module_and_duration() -> None:
    async def _detect(ctx: ScanContext) -> NoReturn:
        raise TimeoutError

    result: ModuleResult[BaseModel] = await run_module(
        module=ModuleName.HEADERS, label="Security headers", ctx=_ctx(), detect=_detect, timeout=3.0
    )
    assert result.status == ModuleStatus.ERROR
    assert result.score is None
    assert result.grade is None
    assert result.data is None
    assert result.findings == []
    assert result.summary == "This check did not complete — try scanning again."
    assert result.error is not None
    assert result.error.code == ModuleErrorCode.MODULE_TIMEOUT
    assert result.error.message == "The security headers check timed out after 3 seconds."


@pytest.mark.asyncio
async def test_a_connection_refused_error_gets_the_generic_safe_message() -> None:
    async def _detect(ctx: ScanContext) -> NoReturn:
        raise ConnectionRefusedError

    result: ModuleResult[BaseModel] = await run_module(
        module=ModuleName.TLS, label="TLS configuration", ctx=_ctx(), detect=_detect
    )
    assert result.error is not None
    assert result.error.code == ModuleErrorCode.CONNECTION_REFUSED
    assert result.error.message == "The connection was refused."


@pytest.mark.asyncio
async def test_an_unrecognised_exception_falls_back_to_unexpected_error() -> None:
    async def _detect(ctx: ScanContext) -> NoReturn:
        raise ValueError("something internal broke")

    result: ModuleResult[BaseModel] = await run_module(
        module=ModuleName.DNS, label="DNS", ctx=_ctx(), detect=_detect
    )
    assert result.error is not None
    assert result.error.code == ModuleErrorCode.UNEXPECTED_ERROR
    # The message is safe — it must never leak the actual exception text.
    assert "something internal broke" not in result.error.message


@pytest.mark.asyncio
async def test_error_message_never_contains_a_traceback_or_library_name() -> None:
    async def _detect(ctx: ScanContext) -> NoReturn:
        import httpx

        raise httpx.ConnectError("Connection refused to 10.0.0.1:443 via _ssl.c:997")

    result: ModuleResult[BaseModel] = await run_module(
        module=ModuleName.HEADERS, label="Security headers", ctx=_ctx(), detect=_detect
    )
    assert result.error is not None
    for leaked in ("httpx", "10.0.0.1", "_ssl.c", "Traceback"):
        assert leaked not in result.error.message
