"""Stage 1 state machine (contract §7.15, spec §5/§10). Every legal
transition in each of the three tables, one representative illegal one per
entity (the SENT -> PENDING example the build prompt names explicitly),
`state_reason`/`scan_error`/timestamp population on every write, the
`paused`-campaign gate that must have real teeth (CONTRACT.md §5 v3.6),
and the v3.7 regenerate path (`READY_FOR_REVIEW` -> `DRAFTED`, its
`gmail_draft_id`/`template_variant` side effects, and its own `paused`
gate)."""

from __future__ import annotations

import uuid

import pytest

from app.enums import (
    OutreachCampaignStatus,
    OutreachDomainState,
    OutreachMessageState,
    OutreachProspectState,
)
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachMessageRecord,
    OutreachProspectRecord,
)
from app.outreach.state_machine import (
    _CAMPAIGN_TRANSITIONS,
    _DOMAIN_TRANSITIONS,
    _MESSAGE_TRANSITIONS,
    _PROSPECT_TRANSITIONS,
    CampaignPausedError,
    IllegalTransitionError,
    transition_campaign,
    transition_domain,
    transition_message,
    transition_prospect,
)

_ACTIVE = OutreachCampaignStatus.DRAFT


def _prospect(state: OutreachProspectState) -> OutreachProspectRecord:
    return OutreachProspectRecord(
        prospect_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        agency_name="Test Agency",
        contact_email="test@example.com",
        state=state.value,
    )


def _domain(state: OutreachDomainState) -> OutreachDomainRecord:
    return OutreachDomainRecord(
        domain_id=uuid.uuid4(),
        prospect_id=uuid.uuid4(),
        hostname="client.example.com",
        state=state.value,
    )


def _campaign(status: OutreachCampaignStatus) -> OutreachCampaignRecord:
    return OutreachCampaignRecord(
        campaign_id=uuid.uuid4(), name="Test campaign", status=status.value
    )


def _message(
    state: OutreachMessageState, *, gmail_draft_id: str | None = None
) -> OutreachMessageRecord:
    return OutreachMessageRecord(
        message_id=uuid.uuid4(),
        prospect_id=uuid.uuid4(),
        hook_code="CERT_EXPIRED",
        hook_domain_id=uuid.uuid4(),
        hook_scan_id=uuid.uuid4(),
        template_variant=1,
        subject="subject",
        body="body",
        state=state.value,
        gmail_draft_id=gmail_draft_id,
    )


def _all_prospect_edges() -> list[tuple[OutreachProspectState, OutreachProspectState]]:
    return [(src, dst) for src, targets in _PROSPECT_TRANSITIONS.items() for dst in targets]


def _all_domain_edges() -> list[tuple[OutreachDomainState, OutreachDomainState]]:
    return [(src, dst) for src, targets in _DOMAIN_TRANSITIONS.items() for dst in targets]


def _all_message_edges() -> list[tuple[OutreachMessageState, OutreachMessageState]]:
    return [(src, dst) for src, targets in _MESSAGE_TRANSITIONS.items() for dst in targets]


@pytest.mark.parametrize("src,dst", _all_prospect_edges())
def test_every_legal_prospect_transition_succeeds(
    src: OutreachProspectState, dst: OutreachProspectState
) -> None:
    prospect = _prospect(src)
    before = prospect.updated_at
    transition_prospect(prospect, dst, campaign_status=_ACTIVE, reason=None)
    assert prospect.state == dst.value
    assert prospect.updated_at != before


@pytest.mark.parametrize("src,dst", _all_domain_edges())
def test_every_legal_domain_transition_succeeds(
    src: OutreachDomainState, dst: OutreachDomainState
) -> None:
    domain = _domain(src)
    before = domain.updated_at
    transition_domain(domain, dst, campaign_status=_ACTIVE, reason=None)
    assert domain.state == dst.value
    assert domain.updated_at != before


@pytest.mark.parametrize("src,dst", _all_message_edges())
def test_every_legal_message_transition_succeeds(
    src: OutreachMessageState, dst: OutreachMessageState
) -> None:
    message = _message(src)
    before = message.state_changed_at
    transition_message(message, dst, campaign_status=_ACTIVE, reason=None)
    assert message.state == dst.value
    assert message.state_changed_at != before


def test_sent_to_pending_is_illegal() -> None:
    """The exact example the build prompt names: SENT -> PENDING is a bug
    and must surface loudly, not silently corrupt a campaign."""
    prospect = _prospect(OutreachProspectState.SENT)
    with pytest.raises(IllegalTransitionError) as exc_info:
        transition_prospect(
            prospect, OutreachProspectState.PENDING, campaign_status=_ACTIVE, reason=None
        )
    assert exc_info.value.entity == "prospect"
    assert prospect.state == OutreachProspectState.SENT.value  # unchanged


def test_illegal_domain_transition_raises() -> None:
    domain = _domain(OutreachDomainState.COMPLETED)
    with pytest.raises(IllegalTransitionError):
        transition_domain(
            domain, OutreachDomainState.RUNNING, campaign_status=_ACTIVE, reason=None
        )


def test_illegal_message_transition_raises() -> None:
    message = _message(OutreachMessageState.DRAFTED)
    with pytest.raises(IllegalTransitionError):
        transition_message(message, OutreachMessageState.SENT, campaign_status=_ACTIVE, reason=None)


@pytest.mark.parametrize(
    "state",
    [
        OutreachProspectState.REPLIED,
        OutreachProspectState.FAILED,
        OutreachProspectState.SKIPPED,
    ],
)
def test_terminal_prospect_states_accept_no_transition(state: OutreachProspectState) -> None:
    prospect = _prospect(state)
    for target in OutreachProspectState:
        if target == state:
            continue
        with pytest.raises(IllegalTransitionError):
            transition_prospect(prospect, target, campaign_status=_ACTIVE, reason=None)


def test_prospect_state_reason_written_on_failure() -> None:
    prospect = _prospect(OutreachProspectState.ANALYZING)
    transition_prospect(
        prospect,
        OutreachProspectState.FAILED,
        campaign_status=_ACTIVE,
        reason="hook selection crashed: no completed domains",
    )
    assert prospect.state_reason == "hook selection crashed: no completed domains"


def test_prospect_state_reason_cleared_when_no_reason_given() -> None:
    prospect = _prospect(OutreachProspectState.ANALYZING)
    prospect.state_reason = "stale reason from a previous failure"
    transition_prospect(
        prospect, OutreachProspectState.DRAFTING, campaign_status=_ACTIVE, reason=None
    )
    assert prospect.state_reason is None


def test_domain_scan_error_written_on_failure() -> None:
    domain = _domain(OutreachDomainState.RUNNING)
    transition_domain(
        domain,
        OutreachDomainState.FAILED,
        campaign_status=_ACTIVE,
        reason="CONNECTION_REFUSED after 2 attempts",
    )
    assert domain.scan_error == "CONNECTION_REFUSED after 2 attempts"


def test_message_state_reason_never_touches_reply_note() -> None:
    """v3.7, human sign-off: state_reason (why the pipeline did something)
    and reply_note (what a human said back) are kept deliberately separate
    — transition_message writes the former and never the latter, even on
    REPLIED, where it would be easy to conflate the two."""
    message = _message(OutreachMessageState.SENT)
    message.reply_note = "pre-existing note a human already wrote"
    transition_message(
        message, OutreachMessageState.REPLIED, campaign_status=_ACTIVE, reason="poll detected reply"
    )
    assert message.state_reason == "poll detected reply"
    assert message.reply_note == "pre-existing note a human already wrote"  # untouched
    assert message.replied_at is not None


def test_message_sent_timestamp_stamped() -> None:
    message = _message(OutreachMessageState.READY_FOR_REVIEW)
    assert message.sent_at is None
    transition_message(message, OutreachMessageState.SENT, campaign_status=_ACTIVE, reason=None)
    assert message.sent_at is not None


def test_regenerate_stamps_drafted_at_nulls_draft_id_and_bumps_variant() -> None:
    """READY_FOR_REVIEW -> DRAFTED ("regenerate", v3.7 human sign-off) has
    exactly one meaning in this graph — see module docstring — so
    transition_message performs its two attribute-only obligations
    directly: null gmail_draft_id (never let it point at a draft about to
    be deleted) and bump template_variant (a message worth re-drafting
    probably read wrong the first time)."""
    message = _message(OutreachMessageState.READY_FOR_REVIEW, gmail_draft_id="r-old-draft-id")
    transition_message(
        message, OutreachMessageState.DRAFTED, campaign_status=_ACTIVE, reason=None
    )
    assert message.state == OutreachMessageState.DRAFTED.value
    assert message.gmail_draft_id is None
    assert message.template_variant == 2
    assert message.drafted_at is not None


def test_regenerate_failure_reason_recorded_while_staying_drafted() -> None:
    """'If a regenerate fails partway, state_reason records it and the
    message stays in DRAFTED' (human sign-off) — the transition itself
    always succeeds atomically; a reason passed alongside it just records
    why the *next* step (creating the replacement draft) hasn't happened
    yet, without moving the state anywhere else."""
    message = _message(OutreachMessageState.READY_FOR_REVIEW, gmail_draft_id="r-old-draft-id")
    transition_message(
        message,
        OutreachMessageState.DRAFTED,
        campaign_status=_ACTIVE,
        reason="Gmail API timed out creating the replacement draft",
    )
    assert message.state == OutreachMessageState.DRAFTED.value
    assert message.state_reason == "Gmail API timed out creating the replacement draft"


def test_regenerate_blocked_when_campaign_paused() -> None:
    """'Stop new drafts being created' (human sign-off, CONTRACT.md §5
    v3.6) covers a regenerated draft too, not only a prospect's first one
    — pausing a campaign should stop all new outbound drafting."""
    message = _message(OutreachMessageState.READY_FOR_REVIEW, gmail_draft_id="r-old-draft-id")
    with pytest.raises(CampaignPausedError):
        transition_message(
            message,
            OutreachMessageState.DRAFTED,
            campaign_status=OutreachCampaignStatus.PAUSED,
            reason=None,
        )
    assert message.state == OutreachMessageState.READY_FOR_REVIEW.value  # unchanged
    assert message.gmail_draft_id == "r-old-draft-id"  # unchanged


def test_non_gated_message_transitions_proceed_when_campaign_paused() -> None:
    message = _message(OutreachMessageState.READY_FOR_REVIEW)
    transition_message(
        message,
        OutreachMessageState.SENT,
        campaign_status=OutreachCampaignStatus.PAUSED,
        reason=None,
    )
    assert message.state == OutreachMessageState.SENT.value


def test_draft_creation_blocked_when_campaign_paused() -> None:
    prospect = _prospect(OutreachProspectState.ANALYZING)
    with pytest.raises(CampaignPausedError):
        transition_prospect(
            prospect,
            OutreachProspectState.DRAFTING,
            campaign_status=OutreachCampaignStatus.PAUSED,
            reason=None,
        )
    assert prospect.state == OutreachProspectState.ANALYZING.value  # unchanged


def test_domain_scan_enqueue_blocked_when_campaign_paused() -> None:
    domain = _domain(OutreachDomainState.PENDING)
    with pytest.raises(CampaignPausedError):
        transition_domain(
            domain,
            OutreachDomainState.RUNNING,
            campaign_status=OutreachCampaignStatus.PAUSED,
            reason=None,
        )
    assert domain.state == OutreachDomainState.PENDING.value  # unchanged


def test_domain_retry_reentering_running_also_blocked_when_paused() -> None:
    """'Block new domain scans being enqueued' (human sign-off, CONTRACT.md
    §5 v3.6) applies to a retry re-entering RUNNING too, not just the first
    attempt from PENDING."""
    domain = _domain(OutreachDomainState.RETRYING)
    with pytest.raises(CampaignPausedError):
        transition_domain(
            domain,
            OutreachDomainState.RUNNING,
            campaign_status=OutreachCampaignStatus.PAUSED,
            reason=None,
        )


def test_non_gated_prospect_transitions_proceed_when_campaign_paused() -> None:
    """Only entry into DRAFTING is gated — a paused campaign must not also
    freeze in-flight scanning/analysis or a human's ability to mark a
    prospect skipped."""
    prospect = _prospect(OutreachProspectState.PENDING)
    transition_prospect(
        prospect,
        OutreachProspectState.SCANNING,
        campaign_status=OutreachCampaignStatus.PAUSED,
        reason=None,
    )
    assert prospect.state == OutreachProspectState.SCANNING.value


def test_non_gated_domain_transitions_proceed_when_campaign_paused() -> None:
    domain = _domain(OutreachDomainState.RUNNING)
    transition_domain(
        domain,
        OutreachDomainState.COMPLETED,
        campaign_status=OutreachCampaignStatus.PAUSED,
        reason=None,
    )
    assert domain.state == OutreachDomainState.COMPLETED.value


# --- Stage 2 (v3.9/v3.10): campaign-status transitions ---


def _all_campaign_edges() -> list[tuple[OutreachCampaignStatus, OutreachCampaignStatus]]:
    return [(src, dst) for src, targets in _CAMPAIGN_TRANSITIONS.items() for dst in targets]


@pytest.mark.parametrize("src,dst", _all_campaign_edges())
def test_every_legal_campaign_transition_succeeds(
    src: OutreachCampaignStatus, dst: OutreachCampaignStatus
) -> None:
    campaign = _campaign(src)
    transition_campaign(campaign, dst, reason=None)
    assert campaign.status == dst.value


def test_illegal_campaign_transition_raises() -> None:
    campaign = _campaign(OutreachCampaignStatus.DRAFT)
    with pytest.raises(IllegalTransitionError):
        transition_campaign(campaign, OutreachCampaignStatus.PAUSED, reason=None)
    assert campaign.status == OutreachCampaignStatus.DRAFT.value  # unchanged


def test_paused_campaign_cannot_go_back_to_draft() -> None:
    campaign = _campaign(OutreachCampaignStatus.PAUSED)
    with pytest.raises(IllegalTransitionError):
        transition_campaign(campaign, OutreachCampaignStatus.DRAFT, reason=None)


def test_complete_campaign_is_terminal() -> None:
    campaign = _campaign(OutreachCampaignStatus.COMPLETE)
    for target in OutreachCampaignStatus:
        if target == OutreachCampaignStatus.COMPLETE:
            continue
        with pytest.raises(IllegalTransitionError):
            transition_campaign(campaign, target, reason=None)
