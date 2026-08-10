"""Shape tests for `GET /api/v1/meta/deadlines` (contract §6.5). No database
or Redis dependency, so this runs anywhere `pytest` runs."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_get_deadlines_returns_the_three_locked_phases(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta/deadlines")
    assert response.status_code == 200
    body = response.json()

    assert "generated_at" in body
    phases_by_name = {phase["phase"]: phase for phase in body["phases"]}
    assert set(phases_by_name) == {"phase_200", "phase_100", "phase_47"}

    assert phases_by_name["phase_200"]["effective_from"] == "2026-03-15"
    assert phases_by_name["phase_200"]["max_lifetime_days"] == 200
    assert phases_by_name["phase_200"]["renewals_per_year"] == 2

    assert phases_by_name["phase_100"]["effective_from"] == "2027-03-15"
    assert phases_by_name["phase_100"]["max_lifetime_days"] == 100
    assert phases_by_name["phase_100"]["renewals_per_year"] == 4

    assert phases_by_name["phase_47"]["effective_from"] == "2029-03-15"
    assert phases_by_name["phase_47"]["max_lifetime_days"] == 47
    assert phases_by_name["phase_47"]["renewals_per_year"] == 8


@pytest.mark.asyncio
async def test_get_deadlines_marks_exactly_one_phase_active(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta/deadlines")
    body = response.json()
    active = [phase for phase in body["phases"] if phase["active"]]
    assert len(active) == 1


@pytest.mark.asyncio
async def test_get_deadlines_next_deadline_is_non_negative_and_consistent(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/meta/deadlines")
    body = response.json()
    next_deadline = body["next_deadline"]
    assert next_deadline["phase"] in {"phase_200", "phase_100", "phase_47"}
    assert next_deadline["days_remaining"] >= 0
    matching_phase = next(p for p in body["phases"] if p["phase"] == next_deadline["phase"])
    assert next_deadline["date"] == matching_phase["effective_from"]
    assert matching_phase["active"] is False
