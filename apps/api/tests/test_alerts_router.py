"""HTTP-level test for GET /api/v1/alerts/unsubscribe/{recipient_id}
(contract §7.10) — no session required, matches an email-click link.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.main import app
from app.models import AlertRecipientRecord, OrganisationRecord


@pytest.fixture
def _wired_app(db_session: AsyncSession) -> Iterator[None]:
    async def _get_session() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _get_session
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(_wired_app: None) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_unsubscribe_marks_the_recipient_unsubscribed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org = OrganisationRecord(org_id=uuid.uuid4(), name="Acme", country="IN", currency="INR")
    db_session.add(org)
    await db_session.commit()
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

    response = await client.get(f"/api/v1/alerts/unsubscribe/{recipient.recipient_id}")
    assert response.status_code == 200
    assert "no longer receive" in response.json()["message"]

    await db_session.refresh(recipient)
    assert recipient.unsubscribed is True


@pytest.mark.asyncio
async def test_unsubscribe_unknown_recipient_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/alerts/unsubscribe/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_unsubscribe_malformed_id_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts/unsubscribe/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
