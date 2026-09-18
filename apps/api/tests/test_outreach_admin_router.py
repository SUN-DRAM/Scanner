"""Stage 1 minimal admin surface (contract §7.15, docs/outreach_stage_1.md
Step 5): the four `/api/v1/admin/outreach/*` routes. Token gate, the
`OutreachImportReport` shape end to end through a real multipart upload,
and that re-importing the same file through the HTTP route is still a
no-op — not just at the `import_csv` unit level (already covered in
`tests/test_outreach_import.py`).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import OutreachCampaignRecord, OutreachProspectRecord

_CLEAN_CSV = b"""agency_name,contact_name,contact_email,agency_website,client_domain
Decipher Zone,Rahul,rahul@dz-rt.example.com,dz-rt.example.com,letshego-rt.example.com
Decipher Zone,Rahul,rahul@dz-rt.example.com,dz-rt.example.com,d101-rt.example.com
ABC Digital,Priya,priya@abc-rt.example.com,abc-rt.example.com,client1-rt.example.com
"""


@pytest.fixture
def admin_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    token = "test-admin-" + uuid.uuid4().hex
    monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()
    yield token
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"X-Admin-Token": token}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def _delete_campaign(session: AsyncSession, campaign_id: str) -> None:
    parsed = uuid.UUID(campaign_id)
    await session.execute(
        delete(OutreachProspectRecord).where(OutreachProspectRecord.campaign_id == parsed)
    )
    await session.execute(
        delete(OutreachCampaignRecord).where(OutreachCampaignRecord.campaign_id == parsed)
    )
    await session.commit()


@pytest.mark.asyncio
async def test_create_campaign_rejects_missing_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/admin/outreach/campaigns", json={"name": "Test campaign"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_campaign_rejects_wrong_token(client: AsyncClient, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/admin/outreach/campaigns",
        headers=_auth("wrong-token"),
        json={"name": "Test campaign"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_campaigns(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    created = await client.post(
        "/api/v1/admin/outreach/campaigns",
        headers=_auth(admin_token),
        json={"name": "Router test campaign"},
    )
    assert created.status_code == 201
    body = created.json()
    campaign_id = body["campaign_id"]
    try:
        assert body["name"] == "Router test campaign"
        assert body["status"] == "draft"

        listed = await client.get(
            "/api/v1/admin/outreach/campaigns", headers=_auth(admin_token)
        )
        assert listed.status_code == 200
        rows = {row["campaign_id"]: row for row in listed.json()["items"]}
        assert campaign_id in rows
        row = rows[campaign_id]
        assert row["prospect_count"] == 0
        assert row["state_counts"]["pending"] == 0
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_create_campaign_rejects_blank_name(client: AsyncClient, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/admin/outreach/campaigns", headers=_auth(admin_token), json={"name": "   "}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_unknown_campaign_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.post(
        f"/api/v1/admin/outreach/campaigns/{uuid.uuid4()}/import",
        headers=_auth(admin_token),
        files={"file": ("agencies.csv", b"agency_name,contact_email,client_domain\n", "text/csv")},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_import_malformed_csv_returns_422(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    created = (
        await client.post(
            "/api/v1/admin/outreach/campaigns",
            headers=_auth(admin_token),
            json={"name": "Malformed import test"},
        )
    ).json()
    campaign_id = created["campaign_id"]
    try:
        bad_csv = b"agency_name,client_domain\nA,x.example.com\n"
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/import",
            headers=_auth(admin_token),
            files={"file": ("agencies.csv", bad_csv, "text/csv")},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_import_report_and_reimport_through_http_is_a_no_op(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    created = (
        await client.post(
            "/api/v1/admin/outreach/campaigns",
            headers=_auth(admin_token),
            json={"name": "End to end import test"},
        )
    ).json()
    campaign_id = created["campaign_id"]
    try:
        first = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/import",
            headers=_auth(admin_token),
            files={"file": ("agencies.csv", _CLEAN_CSV, "text/csv")},
        )
        assert first.status_code == 200
        report = first.json()
        assert report["imported_agencies"] == 2
        assert report["imported_domains"] == 5  # 3 client rows + 2 own domains
        assert report["rejected_rows"] == []

        prospects = await client.get(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/prospects",
            headers=_auth(admin_token),
        )
        assert prospects.status_code == 200
        prospect_body = prospects.json()
        assert prospect_body["total"] == 2
        assert all(item["state"] == "pending" for item in prospect_body["items"])

        filtered = await client.get(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/prospects",
            headers=_auth(admin_token),
            params={"state": "sent"},
        )
        assert filtered.json()["total"] == 0

        listed = await client.get(
            "/api/v1/admin/outreach/campaigns", headers=_auth(admin_token)
        )
        row = next(r for r in listed.json()["items"] if r["campaign_id"] == campaign_id)
        assert row["prospect_count"] == 2
        assert row["state_counts"]["pending"] == 2

        second = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/import",
            headers=_auth(admin_token),
            files={"file": ("agencies.csv", _CLEAN_CSV, "text/csv")},
        )
        assert second.status_code == 200
        second_report = second.json()
        assert second_report["imported_agencies"] == 0
        assert second_report["imported_domains"] == 0
        assert second_report["skipped_agencies"] == 2

        prospects_after = await client.get(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/prospects",
            headers=_auth(admin_token),
        )
        assert prospects_after.json()["total"] == 2  # unchanged
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_list_prospects_unknown_campaign_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.get(
        f"/api/v1/admin/outreach/campaigns/{uuid.uuid4()}/prospects",
        headers=_auth(admin_token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_prospects_malformed_campaign_id_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.get(
        "/api/v1/admin/outreach/campaigns/not-a-uuid/prospects", headers=_auth(admin_token)
    )
    assert response.status_code == 404


# --- §7.16 Stage 2: batch control endpoints ---


async def _new_campaign(client: AsyncClient, admin_token: str, name: str) -> str:
    created = (
        await client.post(
            "/api/v1/admin/outreach/campaigns", headers=_auth(admin_token), json={"name": name}
        )
    ).json()
    return created["campaign_id"]


@pytest.mark.asyncio
async def test_scan_moves_draft_campaign_to_running(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Scan start test")
    try:
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan",
            headers=_auth(admin_token),
            params={"include_weak": "true"},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "running"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_scan_on_already_running_campaign_is_a_status_no_op(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Scan idempotent test")
    try:
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        second = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        assert second.status_code == 202
        assert second.json()["status"] == "running"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_scan_on_paused_campaign_is_rejected(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Scan on paused test")
    try:
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/pause", headers=_auth(admin_token)
        )
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_CAMPAIGN_STATUS"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_pause_running_campaign(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Pause test")
    try:
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/pause", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        assert response.json()["status"] == "paused"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_pause_non_running_campaign_is_rejected(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Pause draft test")
    try:
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/pause", headers=_auth(admin_token)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_CAMPAIGN_STATUS"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_resume_paused_campaign(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Resume test")
    try:
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan", headers=_auth(admin_token)
        )
        await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/pause", headers=_auth(admin_token)
        )
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/resume", headers=_auth(admin_token)
        )
        assert response.status_code == 202
        assert response.json()["status"] == "running"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_resume_non_paused_campaign_is_rejected(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Resume draft test")
    try:
        response = await client.post(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/resume", headers=_auth(admin_token)
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_CAMPAIGN_STATUS"
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_scan_progress_shape_for_empty_campaign(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    campaign_id = await _new_campaign(client, admin_token, "Progress test")
    try:
        response = await client.get(
            f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan-progress",
            headers=_auth(admin_token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["campaign_id"] == campaign_id
        assert body["domain_state_counts"] == {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "completed_partial": 0,
            "retrying": 0,
            "failed": 0,
        }
        assert body["in_flight"] == 0
        assert body["started_at"] is None
        assert body["estimated_completion_at"] is None
        assert body["recent_outcomes"] == []
        assert body["metrics"]["clean_rate"] is None
    finally:
        await _delete_campaign(db_session, campaign_id)


@pytest.mark.asyncio
async def test_scan_progress_unknown_campaign_returns_404(
    client: AsyncClient, admin_token: str
) -> None:
    response = await client.get(
        f"/api/v1/admin/outreach/campaigns/{uuid.uuid4()}/scan-progress",
        headers=_auth(admin_token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_control_endpoints_reject_missing_token(client: AsyncClient) -> None:
    campaign_id = str(uuid.uuid4())
    for method, path in [
        ("post", f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan"),
        ("post", f"/api/v1/admin/outreach/campaigns/{campaign_id}/pause"),
        ("post", f"/api/v1/admin/outreach/campaigns/{campaign_id}/resume"),
        ("get", f"/api/v1/admin/outreach/campaigns/{campaign_id}/scan-progress"),
    ]:
        response = await getattr(client, method)(path)
        assert response.status_code == 403, path
