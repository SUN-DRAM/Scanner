"""Tests for app/alerts.py (contract §7.10 / §Step 5): trigger detection,
dedupe across repeated scans, quiet-hours deferral, critical bypass, digest
batching, and unsubscribe suppression.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import (
    _cert_expiry_candidates,
    _domain_expiry_candidates,
    _grade_regression_candidate,
    _new_critical_finding_candidates,
    compute_scheduled_for,
    deliver_pending_alerts,
    evaluate_and_fire_alerts,
    unsubscribe_recipient,
)
from app.enums import Grade, ModuleName, ModuleStatus, PlanCode, ScanStatus, Severity
from app.models import (
    AlertEventRecord,
    AlertRecipientRecord,
    MonitoredHostnameRecord,
    OrganisationRecord,
)
from app.plans import get_plan
from app.schemas import (
    CertificateData,
    DnsData,
    Finding,
    ModuleResult,
    Modules,
    Scan,
    SeverityCounts,
)


def _certificate_module(
    *, days_until_expiry: int, not_after: datetime
) -> ModuleResult[CertificateData]:
    data = CertificateData(
        subject_common_name="example.com",
        subject_alternative_names=["example.com"],
        issuer_common_name="R11",
        issuer_organization="Let's Encrypt",
        serial_number="00",
        fingerprint_sha256="a" * 64,
        not_before=not_after - timedelta(days=90),
        not_after=not_after,
        lifetime_days=90,
        days_until_expiry=days_until_expiry,
        is_expired=days_until_expiry < 0,
        is_not_yet_valid=False,
        is_self_signed=False,
        is_wildcard=False,
        hostname_matches=True,
        key_algorithm="ECDSA",
        key_size_bits=256,
        signature_algorithm="sha256WithRSAEncryption",
        ocsp_stapling=False,
        sct_count=2,
    )
    return ModuleResult(
        module=ModuleName.CERTIFICATE,
        status=ModuleStatus.OK,
        score=90,
        grade=Grade.A,
        label="Certificate",
        summary="ok",
        checked_at=datetime.now(UTC),
        duration_ms=1,
        findings=[],
        data=data,
        error=None,
    )


def _dns_module(*, days_until_domain_expiry: int | None) -> ModuleResult[DnsData]:
    data = DnsData(
        a_records=["93.184.216.34"],
        aaaa_records=[],
        cname=None,
        nameservers=[],
        mx_records=[],
        caa_records=[],
        caa_present=False,
        dnssec_enabled=False,
        registrar="Example Registrar",
        domain_created_at=None,
        domain_expires_at=None,
        days_until_domain_expiry=days_until_domain_expiry,
    )
    return ModuleResult(
        module=ModuleName.DNS,
        status=ModuleStatus.OK,
        score=90,
        grade=Grade.A,
        label="DNS",
        summary="ok",
        checked_at=datetime.now(UTC),
        duration_ms=1,
        findings=[],
        data=data,
        error=None,
    )


def _finding(code: str, severity: Severity) -> Finding:
    return Finding(
        code=code,
        module=ModuleName.HEADERS,
        severity=severity,
        title=code,
        description=code,
        remediation=code,
        evidence={},
        docs_path=f"/docs/findings/{code.lower().replace('_', '-')}",
    )


def _scan(
    *,
    hostname: str = "example.com",
    grade: Grade | None = Grade.A,
    cert_days: int | None = None,
    domain_days: int | None = None,
    findings: list[Finding] | None = None,
    status: ScanStatus = ScanStatus.COMPLETED,
) -> Scan:
    findings = findings or []
    now = datetime.now(UTC)
    certificate = (
        _certificate_module(days_until_expiry=cert_days, not_after=now + timedelta(days=cert_days))
        if cert_days is not None
        else None
    )
    dns = _dns_module(days_until_domain_expiry=domain_days) if domain_days is not None else None
    return Scan(
        scan_id=str(uuid.uuid4()),
        public_slug=uuid.uuid4().hex[:12],
        hostname=hostname,
        port=443,
        status=status,
        created_at=now,
        started_at=now,
        completed_at=now,
        duration_ms=100,
        cached=False,
        overall_grade=grade,
        overall_score=95,
        headline="",
        share_url="http://localhost/scan/x",
        counts=SeverityCounts(critical=0, high=0, medium=0, low=0, info=0),
        modules=Modules(
            certificate=certificate,
            chain=None,
            tls=None,
            dns=dns,
            email_auth=None,
            headers=None,
            readiness=None,
        ),
        findings=findings,
        error=None,
    )


async def _make_org(session: AsyncSession, **overrides: object) -> OrganisationRecord:
    org = OrganisationRecord(
        org_id=uuid.uuid4(),
        name="Acme",
        country="IN",
        currency="INR",
        plan_code=overrides.get("plan_code", "free"),
    )
    session.add(org)
    await session.commit()
    for key, value in overrides.items():
        if key != "plan_code":
            setattr(org, key, value)
    await session.commit()
    return org


async def _make_monitor(
    session: AsyncSession, org: OrganisationRecord, **overrides: object
) -> MonitoredHostnameRecord:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(),
        org_id=org.org_id,
        hostname=f"{uuid.uuid4().hex}.example.com",
        port=443,
        state="active",
        **overrides,
    )
    session.add(monitor)
    await session.commit()
    return monitor


async def _alerts_for(session: AsyncSession, monitor_id: uuid.UUID) -> list[AlertEventRecord]:
    stmt = select(AlertEventRecord).where(AlertEventRecord.monitor_id == monitor_id)
    return list((await session.execute(stmt)).scalars().all())


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


# --- trigger detection ---


def test_cert_expiry_fires_only_on_a_genuine_crossing() -> None:
    plan = get_plan(PlanCode.FREE)  # alert_lead_days = (14, 3)

    scan = _scan(cert_days=10)
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(), org_id=uuid.uuid4(), hostname="x.example.com", port=443
    )

    # Previously unknown (None) -> 10 days: crosses the 14-day lead, not the 3-day one.
    candidates = _cert_expiry_candidates(monitor, plan, scan, None)
    assert [c.threshold for c in candidates] == ["14"]

    # Already below 14 last time -> still fine this time: no new candidate.
    candidates = _cert_expiry_candidates(monitor, plan, scan, previous_days=13)
    assert candidates == []

    # Crosses both 14 and 3 in one jump (e.g. a missed scan window).
    scan_close = _scan(cert_days=2)
    candidates = _cert_expiry_candidates(monitor, plan, scan_close, previous_days=20)
    assert {c.threshold for c in candidates} == {"14", "3"}
    urgent = {c.threshold: c.urgent for c in candidates}
    assert urgent["3"] is True
    assert urgent["14"] is False


def test_domain_expiry_fires_only_on_a_genuine_crossing() -> None:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(), org_id=uuid.uuid4(), hostname="x.example.com", port=443
    )
    scan = _scan(domain_days=10)

    candidates = _domain_expiry_candidates(monitor, scan, previous_days=None)
    assert {c.threshold for c in candidates} == {"45", "14"}

    candidates = _domain_expiry_candidates(monitor, scan, previous_days=12)
    assert candidates == []


def test_grade_regression_fires_only_on_a_real_drop() -> None:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(), org_id=uuid.uuid4(), hostname="x.example.com", port=443
    )

    dropped = _scan(grade=Grade.C)
    candidate = _grade_regression_candidate(monitor, dropped, previous_grade="A")
    assert candidate is not None
    assert candidate.threshold == "C"

    same = _scan(grade=Grade.C)
    assert _grade_regression_candidate(monitor, same, previous_grade="C") is None

    improved = _scan(grade=Grade.A)
    assert _grade_regression_candidate(monitor, improved, previous_grade="C") is None

    assert _grade_regression_candidate(monitor, dropped, previous_grade=None) is None


def test_new_critical_finding_only_for_codes_not_seen_before() -> None:
    monitor = MonitoredHostnameRecord(
        monitor_id=uuid.uuid4(), org_id=uuid.uuid4(), hostname="x.example.com", port=443
    )
    previous = _scan(findings=[_finding("CERT_WEAK_KEY", Severity.HIGH)])
    current = _scan(
        findings=[
            _finding("CERT_WEAK_KEY", Severity.HIGH),  # already present, not new
            _finding("CERT_SELF_SIGNED", Severity.CRITICAL),  # new
            _finding("HEADERS_MISSING_HSTS", Severity.LOW),  # new, but not high/critical
        ]
    )
    candidates = _new_critical_finding_candidates(monitor, current, previous)
    assert [c.threshold for c in candidates] == ["CERT_SELF_SIGNED"]


# --- quiet hours / digest scheduling ---


def test_urgent_alerts_always_schedule_immediately() -> None:
    org = OrganisationRecord(
        org_id=uuid.uuid4(),
        name="Acme",
        country="IN",
        currency="INR",
        timezone="Asia/Kolkata",
        quiet_hours_start="21:00",
        quiet_hours_end="08:00",
        digest_mode="digest",
        digest_hour=9,
    )
    # 23:00 IST = 17:30 UTC, well inside the default quiet window.
    now = datetime(2026, 1, 15, 17, 30, tzinfo=UTC)
    assert compute_scheduled_for(org, urgent=True, now=now) == now


def test_non_urgent_alert_defers_past_quiet_hours() -> None:
    org = OrganisationRecord(
        org_id=uuid.uuid4(),
        name="Acme",
        country="IN",
        currency="INR",
        timezone="Asia/Kolkata",
        quiet_hours_start="21:00",
        quiet_hours_end="08:00",
        digest_mode="immediate",
        digest_hour=9,
    )
    # 23:00 IST, inside quiet hours; immediate mode, so it should defer only
    # to the quiet window's end (08:00 IST), not to a digest slot.
    now = datetime(2026, 1, 15, 17, 30, tzinfo=UTC)
    scheduled = compute_scheduled_for(org, urgent=False, now=now)
    local = scheduled.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local.hour == 8
    assert local.minute == 0
    assert scheduled > now


def test_digest_mode_defers_to_the_next_digest_hour() -> None:
    org = OrganisationRecord(
        org_id=uuid.uuid4(),
        name="Acme",
        country="IN",
        currency="INR",
        timezone="Asia/Kolkata",
        quiet_hours_start="21:00",
        quiet_hours_end="08:00",
        digest_mode="digest",
        digest_hour=9,
    )
    # 12:00 IST — outside quiet hours, so only digest deferral applies.
    now = datetime(2026, 1, 15, 6, 30, tzinfo=UTC)
    scheduled = compute_scheduled_for(org, urgent=False, now=now)
    local = scheduled.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local.hour == 9
    assert local.date() == (now.astimezone(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1))


# --- dedupe across repeated scans (integration, real db_session) ---


@pytest.mark.asyncio
async def test_dedupe_blocks_a_second_alert_for_the_same_threshold(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)  # cert_not_after None, last_grade None

    scan_a = _scan(hostname=monitor.hostname, cert_days=5)
    await evaluate_and_fire_alerts(db_session, org, monitor, scan_a)

    # monitor.cert_not_after deliberately left untouched (as if two scans
    # completed before either one's update_monitor_after_scan landed) —
    # the crossing check alone would allow a second attempt here; the
    # dedupe guard against an existing pending/sent row is what must catch it.
    scan_b = _scan(hostname=monitor.hostname, cert_days=4)
    await evaluate_and_fire_alerts(db_session, org, monitor, scan_b)

    events = await _alerts_for(db_session, monitor.monitor_id)
    fourteen_day_events = [e for e in events if e.dedupe_key.endswith(":14")]
    assert len(fourteen_day_events) == 1


# --- delivery: digest batching, unsubscribe suppression, retry ---


@pytest.mark.asyncio
async def test_deliver_pending_alerts_batches_same_org_monitor_into_one_email(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    db_session.add(
        AlertRecipientRecord(
            recipient_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=None,
            email="ops@example.com",
            verified=True,
            unsubscribed=False,
        )
    )
    await db_session.commit()

    now = datetime.now(UTC)
    for i in range(3):
        db_session.add(
            AlertEventRecord(
                alert_id=uuid.uuid4(),
                org_id=org.org_id,
                monitor_id=monitor.monitor_id,
                type="cert_expiry",
                state="pending",
                severity="high",
                subject=f"alert {i}",
                dedupe_key=f"{monitor.monitor_id}:cert_expiry:{i}",
                scheduled_for=now - timedelta(minutes=1),
                sent_at=None,
                recipients=[],
                payload={"hostname": monitor.hostname, "body": f"body {i}"},
            )
        )
    await db_session.commit()

    sender = FakeEmailSender()
    delivered = await deliver_pending_alerts(db_session, sender)

    assert delivered == 3
    assert len(sender.sent) == 1
    assert "3 alerts" in sender.sent[0]["subject"]

    events = await _alerts_for(db_session, monitor.monitor_id)
    assert all(event.state == "sent" for event in events)


@pytest.mark.asyncio
async def test_deliver_pending_alerts_suppresses_when_the_only_recipient_unsubscribed(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    recipient = AlertRecipientRecord(
        recipient_id=uuid.uuid4(),
        org_id=org.org_id,
        monitor_id=None,
        email="ops@example.com",
        verified=True,
        unsubscribed=False,
    )
    db_session.add(recipient)
    await db_session.commit()

    await unsubscribe_recipient(db_session, recipient.recipient_id)

    db_session.add(
        AlertEventRecord(
            alert_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=monitor.monitor_id,
            type="cert_expiry",
            state="pending",
            severity="high",
            subject="alert",
            dedupe_key=f"{monitor.monitor_id}:cert_expiry:7",
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
            sent_at=None,
            recipients=[],
            payload={"hostname": monitor.hostname, "body": "body"},
        )
    )
    await db_session.commit()

    sender = FakeEmailSender()
    delivered = await deliver_pending_alerts(db_session, sender)

    assert delivered == 0
    assert sender.sent == []
    events = await _alerts_for(db_session, monitor.monitor_id)
    assert events[0].state == "suppressed"


@pytest.mark.asyncio
async def test_unsubscribe_recipient_marks_it_unsubscribed(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    recipient = AlertRecipientRecord(
        recipient_id=uuid.uuid4(),
        org_id=org.org_id,
        monitor_id=None,
        email="ops@example.com",
        verified=True,
        unsubscribed=False,
    )
    db_session.add(recipient)
    await db_session.commit()

    result = await unsubscribe_recipient(db_session, recipient.recipient_id)
    assert result is not None
    assert result.unsubscribed is True

    assert await unsubscribe_recipient(db_session, uuid.uuid4()) is None


class FailingEmailSender:
    async def send(self, *, to: str, subject: str, text: str) -> None:
        from app.notify.email import EmailSendError

        raise EmailSendError("simulated provider failure")


@pytest.mark.asyncio
async def test_delivery_failure_retries_then_marks_failed_after_three_attempts(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    monitor = await _make_monitor(db_session, org)
    db_session.add(
        AlertRecipientRecord(
            recipient_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=None,
            email="ops@example.com",
            verified=True,
            unsubscribed=False,
        )
    )
    db_session.add(
        AlertEventRecord(
            alert_id=uuid.uuid4(),
            org_id=org.org_id,
            monitor_id=monitor.monitor_id,
            type="cert_expiry",
            state="pending",
            severity="high",
            subject="alert",
            dedupe_key=f"{monitor.monitor_id}:cert_expiry:7",
            scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
            sent_at=None,
            recipients=[],
            payload={"hostname": monitor.hostname, "body": "body"},
        )
    )
    await db_session.commit()

    sender = FailingEmailSender()
    for attempt in range(1, 4):
        delivered = await deliver_pending_alerts(db_session, sender)
        assert delivered == 0
        events = await _alerts_for(db_session, monitor.monitor_id)
        assert events[0].send_attempts == attempt
        expected_state = "failed" if attempt >= 3 else "pending"
        assert events[0].state == expected_state

    # A permanently-failed event is never picked up again.
    delivered_again = await deliver_pending_alerts(db_session, sender)
    assert delivered_again == 0
    events = await _alerts_for(db_session, monitor.monitor_id)
    assert events[0].send_attempts == 3
