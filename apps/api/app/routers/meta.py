"""`GET /api/v1/meta/deadlines` (contract §6.5).

The phase constants and countdown math live in `app.scanner.readiness` —
the same module the `readiness` scan module uses — so this endpoint and
every scan's `readiness.data` are computed from one source of truth.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.scanner.readiness import PHASES, current_phase, next_deadline_constant
from app.schemas import MetaDeadlines, NextDeadlineInfo, PhaseInfo

router = APIRouter(tags=["meta"])


@router.get("/meta/deadlines", response_model=MetaDeadlines)
async def get_deadlines() -> MetaDeadlines:
    now = datetime.now(UTC)
    active_phase = current_phase(now)
    next_phase = next_deadline_constant(now)

    return MetaDeadlines(
        generated_at=now,
        phases=[
            PhaseInfo(
                phase=constant.phase,
                effective_from=constant.effective_from,
                max_lifetime_days=constant.max_lifetime_days,
                dcv_reuse_days=constant.dcv_reuse_days,
                renewals_per_year=constant.renewals_per_year,
                active=constant.phase == active_phase,
            )
            for constant in PHASES
        ],
        next_deadline=NextDeadlineInfo(
            phase=next_phase.phase,
            date=next_phase.effective_from,
            days_remaining=(next_phase.effective_from - now.date()).days,
        ),
    )
