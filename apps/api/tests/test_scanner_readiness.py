"""Tests for the `readiness` module — the phase/countdown math is pure and
tested with fixed dates; the verdict rules are verified against real
certificates for the two scenarios the phase prompt's acceptance criteria
name explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.enums import LifetimePhase, ReadinessVerdict
from app.scanner import ScanContext
from app.scanner.certificate import run as run_certificate
from app.scanner.readiness import current_phase, next_deadline_constant, phase_label, run


def _ctx(hostname: str, port: int = 443, now: datetime | None = None) -> ScanContext:
    return ScanContext(hostname=hostname, port=port, now=now or datetime.now(UTC))


# --- pure phase/countdown math (no network) ---


def test_current_phase_before_march_2026_is_pre_2026() -> None:
    assert current_phase(datetime(2026, 1, 1, tzinfo=UTC)) == LifetimePhase.PRE_2026


def test_current_phase_on_the_boundary_dates() -> None:
    assert current_phase(datetime(2026, 3, 15, tzinfo=UTC)) == LifetimePhase.PHASE_200
    assert current_phase(datetime(2027, 3, 14, tzinfo=UTC)) == LifetimePhase.PHASE_200
    assert current_phase(datetime(2027, 3, 15, tzinfo=UTC)) == LifetimePhase.PHASE_100
    assert current_phase(datetime(2029, 3, 15, tzinfo=UTC)) == LifetimePhase.PHASE_47


def test_next_deadline_from_phase_200_is_phase_100() -> None:
    constant = next_deadline_constant(datetime(2026, 8, 10, tzinfo=UTC))
    assert constant.phase == LifetimePhase.PHASE_100
    assert constant.effective_from.isoformat() == "2027-03-15"


def test_phase_label_matches_contract_example_wording() -> None:
    assert phase_label(LifetimePhase.PHASE_200) == "200-day maximum (in force since 15 March 2026)"


# --- verdict rules, against real certificates ---


@pytest.mark.asyncio
async def test_90_day_lets_encrypt_certificate_is_automated_and_survives_2027(
    require_internet: None,
) -> None:
    ctx = _ctx("letsencrypt.org")
    cert_result = await run_certificate(ctx)
    assert cert_result.data is not None
    assert cert_result.data.lifetime_days <= 100
    assert "let's encrypt" in cert_result.data.issuer_organization.lower()

    result = await run(ctx, cert_result)
    assert result.data is not None
    assert result.data.verdict == ReadinessVerdict.AUTOMATED
    assert result.data.survives_2027 is True
    assert any(f.code == "READINESS_OK" for f in result.findings)


@pytest.mark.asyncio
async def test_long_lifetime_certificate_is_manual_with_finding(require_internet: None) -> None:
    # untrusted-root.badssl.com's leaf is issued for ~2 years — well over the
    # 100-day cap, exercising the same ">100 days -> manual" rule the
    # acceptance criteria's "398-day certificate" example is about.
    ctx = _ctx("untrusted-root.badssl.com")
    cert_result = await run_certificate(ctx)
    assert cert_result.data is not None
    assert cert_result.data.lifetime_days > 100

    result = await run(ctx, cert_result)
    assert result.data is not None
    assert result.data.verdict == ReadinessVerdict.MANUAL
    assert any(f.code == "READINESS_MANUAL_2027" for f in result.findings)


@pytest.mark.asyncio
async def test_unknown_verdict_when_certificate_module_errored(require_internet: None) -> None:
    ctx = _ctx("this-domain-should-not-exist-sundram.invalid")
    cert_result = await run_certificate(ctx)
    assert cert_result.data is None

    result = await run(ctx, cert_result)
    assert result.data is not None
    assert result.data.verdict == ReadinessVerdict.UNKNOWN
    assert result.data.current_lifetime_days is None
    assert result.data.survives_2027 is None
    assert result.findings == []
