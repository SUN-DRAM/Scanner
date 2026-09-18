"""Stage 1 CSV import (contract §7.15, spec §17). The idempotency test is
the point of this step — see `test_reimporting_same_file_is_a_no_op`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiException, ErrorCode
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachProspectRecord,
    OutreachSuppressionRecord,
)
from app.outreach.importer import import_csv

pytestmark = pytest.mark.asyncio


async def _delete_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Prospects cascade-delete their own domains/messages; the campaign FK
    is deliberately RESTRICT (CONTRACT.md §11), so the campaign itself can
    only be deleted once every prospect referencing it is gone."""
    await session.execute(
        delete(OutreachProspectRecord).where(OutreachProspectRecord.campaign_id == campaign_id)
    )
    await session.execute(
        delete(OutreachCampaignRecord).where(OutreachCampaignRecord.campaign_id == campaign_id)
    )
    await session.commit()


@pytest.fixture
async def campaign_id(db_session: AsyncSession) -> AsyncGenerator[uuid.UUID]:
    record = OutreachCampaignRecord(campaign_id=uuid.uuid4(), name="Test campaign", status="draft")
    db_session.add(record)
    await db_session.commit()
    try:
        yield record.campaign_id
    finally:
        await _delete_campaign(db_session, record.campaign_id)


async def _prospect_count(session: AsyncSession, campaign_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(OutreachProspectRecord)
            .where(OutreachProspectRecord.campaign_id == campaign_id)
        )
    ).scalar_one()


async def _domain_count(session: AsyncSession, campaign_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(OutreachDomainRecord)
            .join(
                OutreachProspectRecord,
                OutreachProspectRecord.prospect_id == OutreachDomainRecord.prospect_id,
            )
            .where(OutreachProspectRecord.campaign_id == campaign_id)
        )
    ).scalar_one()


_CLEAN_CSV = """agency_name,contact_name,contact_email,agency_website,client_domain
Decipher Zone,Rahul,rahul@dz-test.example.com,dz-test.example.com,letshego-test.example.com
Decipher Zone,Rahul,rahul@dz-test.example.com,dz-test.example.com,d101-test.example.com
ABC Digital,Priya,priya@abc-test.example.com,abc-test.example.com,client1-test.example.com
ABC Digital,Priya,priya@abc-test.example.com,abc-test.example.com,client2-test.example.com
"""


async def test_reimporting_same_file_is_a_no_op(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    first = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=_CLEAN_CSV.encode())
    assert first.imported_agencies == 2
    # 4 client rows + 2 "own" domains (one per agency's agency_website,
    # deduped within each agency but each agency has a distinct website)
    assert first.imported_domains == 6
    assert first.skipped_agencies == 0
    assert first.suppressed_agencies == 0
    assert first.rejected_rows == []

    prospects_after_first = await _prospect_count(db_session, campaign_id)
    domains_after_first = await _domain_count(db_session, campaign_id)

    second = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=_CLEAN_CSV.encode())
    assert second.imported_agencies == 0
    assert second.imported_domains == 0
    assert second.skipped_agencies == 2
    assert second.suppressed_agencies == 0
    assert second.rejected_rows == []
    assert second.warnings == []

    assert await _prospect_count(db_session, campaign_id) == prospects_after_first
    assert await _domain_count(db_session, campaign_id) == domains_after_first


async def test_import_creates_agency_domain_for_agency_website(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=_CLEAN_CSV.encode())
    assert report.imported_agencies == 2

    prospect = await db_session.scalar(
        select(OutreachProspectRecord).where(
            OutreachProspectRecord.campaign_id == campaign_id,
            OutreachProspectRecord.contact_email == "rahul@dz-test.example.com",
        )
    )
    assert prospect is not None
    assert prospect.state == "pending"
    assert prospect.agency_website == "dz-test.example.com"

    domains = (
        (
            await db_session.execute(
                select(OutreachDomainRecord).where(
                    OutreachDomainRecord.prospect_id == prospect.prospect_id
                )
            )
        )
        .scalars()
        .all()
    )
    own_domains = [d for d in domains if d.relationship_ == "own"]
    assert len(own_domains) == 1
    assert own_domains[0].hostname == "dz-test.example.com"
    assert all(d.state == "pending" for d in domains)
    # 2 client rows + 1 deduped "own" row, not 3 separate own rows
    assert len(domains) == 3


async def test_import_rejects_row_missing_required_column(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = (
        "agency_name,contact_email,client_domain\n"
        "Good Agency,good@goodagency-test.example.com,goodclient-test.example.com\n"
        ",missing-name@example.com,client-test.example.com\n"
        "Another Agency,,client2-test.example.com\n"
    )
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert report.imported_agencies == 1
    assert [r.reason for r in report.rejected_rows] == [
        "missing agency_name",
        "missing contact_email",
    ]
    assert [r.row_number for r in report.rejected_rows] == [2, 3]


async def test_import_rejects_invalid_hostname_row(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = (
        "agency_name,contact_email,client_domain\n"
        "Bad Host Agency,badhost@badhostagency-test.example.com,not a host\n"
    )
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert report.imported_agencies == 0
    assert len(report.rejected_rows) == 1
    assert report.rejected_rows[0].row_number == 1
    assert "invalid client_domain" in report.rejected_rows[0].reason


async def test_import_rejects_generic_contact_email(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = (
        "agency_name,contact_email,client_domain\n"
        "Some Agency,info@someagency-test.example.com,someclient-test.example.com\n"
    )
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert report.imported_agencies == 0
    assert "generic contact_email" in report.rejected_rows[0].reason


async def test_import_skips_suppressed_email(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    suppressed_email = "suppressed@suppressed-test.example.com"
    db_session.add(OutreachSuppressionRecord(email=suppressed_email, reason="opted_out"))
    await db_session.commit()
    try:
        csv_text = (
            "agency_name,contact_email,client_domain\n"
            f"Suppressed Agency,{suppressed_email},suppressedclient-test.example.com\n"
        )
        report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
        assert report.imported_agencies == 0
        assert report.suppressed_agencies == 1
        assert await _prospect_count(db_session, campaign_id) == 0
    finally:
        await db_session.execute(
            delete(OutreachSuppressionRecord).where(
                OutreachSuppressionRecord.email == suppressed_email
            )
        )
        await db_session.commit()


async def test_import_warns_on_agency_name_conflict(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = (
        "agency_name,contact_email,client_domain\n"
        "First Name,conflict@conflictagency-test.example.com,client1-conflict-test.example.com\n"
        "Second Name,conflict@conflictagency-test.example.com,client2-conflict-test.example.com\n"
    )
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert report.imported_agencies == 1
    assert report.imported_domains == 2
    assert len(report.warnings) == 1
    assert "agency_name differs" in report.warnings[0].message

    prospect = await db_session.scalar(
        select(OutreachProspectRecord).where(
            OutreachProspectRecord.campaign_id == campaign_id,
            OutreachProspectRecord.contact_email == "conflict@conflictagency-test.example.com",
        )
    )
    assert prospect is not None
    assert prospect.agency_name == "First Name"


async def test_import_drops_invalid_agency_website_with_warning(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = (
        "agency_name,contact_email,client_domain,agency_website\n"
        "Blocked Website Agency,blockedwebsite@blockedwebsiteagency-test.example.com,"
        "client-test.example.com,127.0.0.1\n"
    )
    report = await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert report.imported_agencies == 1
    assert report.imported_domains == 1  # client domain only, agency_website dropped
    assert len(report.warnings) == 1
    assert "agency_website" in report.warnings[0].message


async def test_import_caps_row_count(
    db_session: AsyncSession, campaign_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _FakeSettings:
        outreach_max_import_rows = 2

    monkeypatch.setattr("app.outreach.importer.get_settings", lambda: _FakeSettings())

    csv_text = "agency_name,contact_email,client_domain\n" + "".join(
        f"Agency {i},agency{i}@capagency{i}-test.example.com,client{i}-test.example.com\n"
        for i in range(3)
    )
    with pytest.raises(ApiException) as exc_info:
        await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR
    assert await _prospect_count(db_session, campaign_id) == 0


async def test_import_rejects_file_with_no_data_rows(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = "agency_name,contact_email,client_domain\n"
    with pytest.raises(ApiException) as exc_info:
        await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_import_rejects_missing_required_header_column(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    csv_text = "agency_name,client_domain\nAgency,client-test.example.com\n"
    with pytest.raises(ApiException) as exc_info:
        await import_csv(db_session, campaign_id=campaign_id, csv_bytes=csv_text.encode())
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR
    assert "contact_email" in exc_info.value.message


async def test_import_rejects_invalid_utf8(
    db_session: AsyncSession, campaign_id: uuid.UUID
) -> None:
    with pytest.raises(ApiException) as exc_info:
        await import_csv(db_session, campaign_id=campaign_id, csv_bytes=b"\xff\xfe\x00not utf8")
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_import_unknown_campaign_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(ApiException) as exc_info:
        await import_csv(
            db_session,
            campaign_id=uuid.uuid4(),
            csv_bytes=b"agency_name,contact_email,client_domain\n",
        )
    assert exc_info.value.code == ErrorCode.NOT_FOUND
