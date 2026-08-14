"""Tests for app/plans.py against contract §5.1's pricing table."""

from __future__ import annotations

from app.enums import PlanCode
from app.plans import get_plan, next_purchasable_plan


def test_free_plan_matches_contract_table() -> None:
    plan = get_plan(PlanCode.FREE)
    assert plan.hostname_limit == 3
    assert plan.scan_interval_hours == 24
    assert plan.alert_lead_days == (14, 3)
    assert plan.member_limit == 1
    assert plan.inr_minor_monthly == 0
    assert plan.usd_minor_monthly == 0
    assert plan.purchasable is True


def test_watch_plan_matches_contract_table() -> None:
    plan = get_plan(PlanCode.WATCH)
    assert plan.hostname_limit == 25
    assert plan.scan_interval_hours == 6
    assert plan.alert_lead_days == (60, 30, 14, 7, 3, 1)
    assert plan.member_limit == 3
    assert plan.inr_minor_monthly == 99_900
    assert plan.usd_minor_monthly == 2_900
    assert plan.purchasable is True


def test_watch_pro_plan_matches_contract_table() -> None:
    plan = get_plan(PlanCode.WATCH_PRO)
    assert plan.hostname_limit == 100
    assert plan.scan_interval_hours == 6
    assert plan.alert_lead_days == (60, 30, 14, 7, 3, 1)
    assert plan.member_limit == 10
    assert plan.inr_minor_monthly == 299_900
    assert plan.usd_minor_monthly == 7_900
    assert plan.purchasable is True


def test_secure_and_compliance_exist_but_are_not_purchasable() -> None:
    for code in (PlanCode.SECURE, PlanCode.COMPLIANCE):
        plan = get_plan(code)
        assert plan.purchasable is False
        # Not specified numerically by the phase prompt (Phase 3 concern) —
        # None means "not enforced here", never a guessed number.
        assert plan.hostname_limit is None
        assert plan.scan_interval_hours is None
        assert plan.member_limit is None


def test_next_purchasable_plan_ordering() -> None:
    assert next_purchasable_plan(PlanCode.FREE) == PlanCode.WATCH
    assert next_purchasable_plan(PlanCode.WATCH) == PlanCode.WATCH_PRO
    assert next_purchasable_plan(PlanCode.WATCH_PRO) is None
    assert next_purchasable_plan(PlanCode.SECURE) is None
    assert next_purchasable_plan(PlanCode.COMPLIANCE) is None
