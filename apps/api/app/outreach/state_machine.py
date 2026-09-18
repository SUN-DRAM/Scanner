"""The outreach state machine (contract §7.15/§11, spec §5, §10). The one
module that owns every `OutreachProspectState`/`OutreachDomainState`/
`OutreachMessageState` transition — no state string is ever assigned to a
record anywhere else in this codebase. "This module is the spine of
stages 2 through 5" (docs/outreach_stage_1.md, Step 4).

**Illegal transitions raise, on purpose.** `IllegalTransitionError` and
`CampaignPausedError` are plain `Exception`s, not `ApiException` — they are
not part of the JSON error contract (§7.4). A caller hitting one is a bug
(`SENT` → `PENDING` corrupting a campaign) or an operational block worth a
loud failure, not a normal request-validation outcome a client should
handle gracefully. Let it propagate as an unhandled 500 and surface in
Sentry rather than being swallowed into a polite error envelope.

**Transitions mutate, callers persist.** These functions only set
attributes (`state`, `updated_at`, and the entity's own failure-reason
field) on the ORM instance already loaded in the caller's session — they
never call `session.commit()` themselves, so a caller can batch several
transitions (e.g. a whole CSV import) into one commit, matching every
other module in this codebase.

**`paused` has real teeth (human sign-off, CONTRACT.md §5/§14 v3.6):**
entering `OutreachDomainState.RUNNING` (a scan is about to be enqueued) or
`OutreachProspectState.DRAFTING`/`OutreachMessageState.DRAFTED` (a draft
— first-time or regenerated — is about to be generated) raises
`CampaignPausedError` when the owning campaign's status is `paused`. Every
caller of `transition_domain`/`transition_prospect`/`transition_message`
must pass `campaign_status` — it is not optional and has no default, so
this check cannot be skipped by omission the way an ad-hoc `if
campaign.status != "paused":` scattered at each call site could be
forgotten.

**`state_reason`/`state_changed_at` (v3.7, human sign-off — CONTRACT.md
§11).** What was a known gap in v3.6 (no column on `outreach_messages` to
persist a failure reason or a generic "when did this last change") is
resolved: `state_reason` mirrors `outreach_prospects.state_reason` (why a
transition failed — a Gmail API rejection, a PDF that wouldn't render, an
oversized attachment — surfaced on the review page, not left to a log
grep), distinct from `reply_note` (what a human said back). A single
`state_changed_at`, not one nullable timestamp per state, is written on
*every* transition — "sitting in `READY_FOR_REVIEW` for six days" is
answerable from that column alone. `drafted_at`/`sent_at`/`replied_at`
are unchanged and still the ones spec §12's metrics read.

**Regenerate (v3.7, human sign-off — CONTRACT.md §11): `READY_FOR_REVIEW`
→ `DRAFTED` is now a legal edge.** `outreach_messages` stays
`unique(prospect_id)` — regenerate updates the existing row, never
inserts a second one; that uniqueness is the table's own idempotency key
(spec §10), not merely a constraint. `DRAFTED` has exactly one incoming
edge in the whole graph, so a transition *into* it can only ever mean
"regenerate" (a message's *first* entry into `DRAFTED` happens at row
creation, which never calls this function at all — same as prospects and
domains starting at `PENDING`). Two caller obligations bind whoever
builds this in spec Stage 4, not this module: delete the old Gmail draft
via the API before creating the replacement, and null `gmail_draft_id` as
part of that same step so the column never transiently holds an id Gmail
no longer has. `transition_message` performs its own half directly —
nulling `gmail_draft_id` and bumping `template_variant` on entry to
`DRAFTED` — since both are plain attribute mutations this function can
safely own; the Gmail API call itself is out of reach here (no Gmail
client exists yet, and Stage 4 — "templates, PDF attach, Gmail draft
creation" — is where one will). If the new draft's creation then fails
partway, the message simply stays at `DRAFTED` with `state_reason` set —
visibly incomplete on the review page rather than silently stale. `SENT`
is unchanged and still reaches only `REPLIED`: regenerating a sent
message would misrepresent what actually left the building.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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

logger = logging.getLogger("app.outreach.state_machine")


class OutreachStateError(Exception):
    """Base of both state-machine exceptions — catch this to handle either
    without caring which one fired."""


class IllegalTransitionError(OutreachStateError):
    def __init__(
        self,
        entity: str,
        entity_id: uuid.UUID,
        from_state: str,
        to_state: str,
    ) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Illegal {entity} transition {from_state} -> {to_state} ({entity_id})"
        )


class CampaignPausedError(OutreachStateError):
    def __init__(self, entity: str, entity_id: uuid.UUID, to_state: str) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.to_state = to_state
        super().__init__(
            f"Campaign is paused: refusing to move {entity} {entity_id} to {to_state}"
        )


# --- §5.1: one email per agency, aggregated across its whole portfolio ---
# SKIPPED is reachable from every non-terminal state ("manually excluded",
# spec §5.1) except the three that are already terminal outcomes in their
# own right (SENT/REPLIED's pipeline has already produced its result;
# FAILED is already the excluded-with-a-reason state). SUPPRESSED is the
# one state with an explicit way back in ("revisit in 60 days", spec §6.3)
# — FAILED has no such language and is treated as terminal, deliberately
# asymmetric with SUPPRESSED rather than assumed identical.
_PROSPECT_TRANSITIONS: dict[OutreachProspectState, frozenset[OutreachProspectState]] = {
    OutreachProspectState.PENDING: frozenset(
        {OutreachProspectState.SCANNING, OutreachProspectState.SKIPPED}
    ),
    OutreachProspectState.SCANNING: frozenset(
        {
            OutreachProspectState.ANALYZING,
            OutreachProspectState.FAILED,
            OutreachProspectState.SKIPPED,
        }
    ),
    OutreachProspectState.ANALYZING: frozenset(
        {
            OutreachProspectState.SUPPRESSED,
            OutreachProspectState.DRAFTING,
            OutreachProspectState.FAILED,
            OutreachProspectState.SKIPPED,
        }
    ),
    OutreachProspectState.SUPPRESSED: frozenset(
        {OutreachProspectState.PENDING, OutreachProspectState.SKIPPED}
    ),
    OutreachProspectState.DRAFTING: frozenset(
        {
            OutreachProspectState.READY_FOR_REVIEW,
            OutreachProspectState.FAILED,
            OutreachProspectState.SKIPPED,
        }
    ),
    OutreachProspectState.READY_FOR_REVIEW: frozenset(
        {
            OutreachProspectState.SENT,
            OutreachProspectState.DRAFTING,  # "regenerate" (spec §11 review UI)
            OutreachProspectState.SKIPPED,
        }
    ),
    OutreachProspectState.SENT: frozenset({OutreachProspectState.REPLIED}),
    OutreachProspectState.REPLIED: frozenset(),
    OutreachProspectState.FAILED: frozenset(),
    OutreachProspectState.SKIPPED: frozenset(),
}

# --- §5.2: RETRYING/COMPLETED_PARTIAL model the "re-scanned once after
# RETRY_BACKOFF_SECONDS" rule structurally; the "only once" *count* is the
# caller's business rule (checked against scan_attempts before it ever
# calls this function), not something transition legality enforces — this
# module answers "is this move structurally legal", not "should it happen
# right now". ---
_DOMAIN_TRANSITIONS: dict[OutreachDomainState, frozenset[OutreachDomainState]] = {
    OutreachDomainState.PENDING: frozenset({OutreachDomainState.RUNNING}),
    OutreachDomainState.RUNNING: frozenset(
        {
            OutreachDomainState.COMPLETED,
            OutreachDomainState.COMPLETED_PARTIAL,
            OutreachDomainState.RETRYING,
            OutreachDomainState.FAILED,
        }
    ),
    OutreachDomainState.RETRYING: frozenset({OutreachDomainState.RUNNING}),
    OutreachDomainState.COMPLETED_PARTIAL: frozenset({OutreachDomainState.RETRYING}),
    OutreachDomainState.COMPLETED: frozenset(),
    OutreachDomainState.FAILED: frozenset(),
}

# --- §5.3, v3.7: the spec's diagram, plus the READY_FOR_REVIEW -> DRAFTED
# back-edge ("regenerate") added in the same amendment — see this module's
# docstring for the two caller obligations that edge implies. ---
_MESSAGE_TRANSITIONS: dict[OutreachMessageState, frozenset[OutreachMessageState]] = {
    OutreachMessageState.DRAFTED: frozenset({OutreachMessageState.READY_FOR_REVIEW}),
    OutreachMessageState.READY_FOR_REVIEW: frozenset(
        {
            OutreachMessageState.SENT,
            OutreachMessageState.DISCARDED,
            OutreachMessageState.DRAFTED,  # "regenerate" (spec §11 review UI)
        }
    ),
    OutreachMessageState.SENT: frozenset({OutreachMessageState.REPLIED}),
    OutreachMessageState.REPLIED: frozenset(),
    OutreachMessageState.DISCARDED: frozenset(),
}

# --- Campaign status (§7.16, v3.9/v3.10) — a gap the Stage 1 build never
# named: nothing needed campaign-level transitions before Stage 2's
# .../scan/.../pause/.../resume endpoints. No edge back to `draft` (a
# campaign that's ever run stays past that point), no way to pause a
# `draft` campaign (pausing something never running means nothing), and
# `running -> complete` exists but no Stage 2 code path ever takes it —
# Stage 5's concern, same "defined now, used later" treatment
# outreach_messages got in v3.6. ---
_CAMPAIGN_TRANSITIONS: dict[OutreachCampaignStatus, frozenset[OutreachCampaignStatus]] = {
    OutreachCampaignStatus.DRAFT: frozenset({OutreachCampaignStatus.RUNNING}),
    OutreachCampaignStatus.RUNNING: frozenset(
        {OutreachCampaignStatus.PAUSED, OutreachCampaignStatus.COMPLETE}
    ),
    OutreachCampaignStatus.PAUSED: frozenset({OutreachCampaignStatus.RUNNING}),
    OutreachCampaignStatus.COMPLETE: frozenset(),
}

# Target states that require an active (non-paused) campaign to enter.
_PROSPECT_REQUIRES_ACTIVE_CAMPAIGN: frozenset[OutreachProspectState] = frozenset(
    {OutreachProspectState.DRAFTING}
)
_DOMAIN_REQUIRES_ACTIVE_CAMPAIGN: frozenset[OutreachDomainState] = frozenset(
    {OutreachDomainState.RUNNING}
)
_MESSAGE_REQUIRES_ACTIVE_CAMPAIGN: frozenset[OutreachMessageState] = frozenset(
    {OutreachMessageState.DRAFTED}
)


@dataclass(frozen=True)
class _Move:
    entity: str
    entity_id: uuid.UUID
    from_state: str
    to_state: str


def _check_legal(
    table: dict[object, frozenset[object]], move: _Move, current: object, to: object
) -> None:
    if to not in table.get(current, frozenset()):
        logger.error(
            f"{move.entity}_transition_illegal",
            extra={
                f"{move.entity}_id": str(move.entity_id),
                "from": move.from_state,
                "to": move.to_state,
            },
        )
        raise IllegalTransitionError(move.entity, move.entity_id, move.from_state, move.to_state)


def _check_campaign_active(
    move: _Move, to: object, gated: frozenset[object], campaign_status: OutreachCampaignStatus
) -> None:
    if to in gated and campaign_status == OutreachCampaignStatus.PAUSED:
        logger.warning(
            f"{move.entity}_transition_blocked_paused",
            extra={f"{move.entity}_id": str(move.entity_id), "to": move.to_state},
        )
        raise CampaignPausedError(move.entity, move.entity_id, move.to_state)


def transition_prospect(
    prospect: OutreachProspectRecord,
    to: OutreachProspectState,
    *,
    campaign_status: OutreachCampaignStatus,
    reason: str | None,
) -> None:
    current = OutreachProspectState(prospect.state)
    move = _Move("prospect", prospect.prospect_id, current.value, to.value)
    _check_legal(_PROSPECT_TRANSITIONS, move, current, to)  # type: ignore[arg-type]
    _check_campaign_active(move, to, _PROSPECT_REQUIRES_ACTIVE_CAMPAIGN, campaign_status)

    prospect.state = to.value
    prospect.state_reason = reason
    prospect.updated_at = datetime.now(UTC)
    logger.info(
        "prospect_transition",
        extra={"prospect_id": str(prospect.prospect_id), "from": current.value, "to": to.value},
    )


def transition_domain(
    domain: OutreachDomainRecord,
    to: OutreachDomainState,
    *,
    campaign_status: OutreachCampaignStatus,
    reason: str | None,
) -> None:
    current = OutreachDomainState(domain.state)
    move = _Move("domain", domain.domain_id, current.value, to.value)
    _check_legal(_DOMAIN_TRANSITIONS, move, current, to)  # type: ignore[arg-type]
    _check_campaign_active(move, to, _DOMAIN_REQUIRES_ACTIVE_CAMPAIGN, campaign_status)

    domain.state = to.value
    # The domain's own failure-reason column (§11) — see module docstring.
    domain.scan_error = reason
    domain.updated_at = datetime.now(UTC)
    logger.info(
        "domain_transition",
        extra={"domain_id": str(domain.domain_id), "from": current.value, "to": to.value},
    )


def transition_message(
    message: OutreachMessageRecord,
    to: OutreachMessageState,
    *,
    campaign_status: OutreachCampaignStatus,
    reason: str | None,
) -> None:
    """`reason` always writes `state_reason` (v3.7) — never `reply_note`.
    They're kept deliberately separate (human sign-off): `reply_note` is
    what a human said back and is set independently of this function,
    wherever a reply's content gets recorded; `state_reason` is why the
    *pipeline* did or didn't do something, the same role
    `OutreachProspectRecord.state_reason` plays.

    Entry to `DRAFTED` is "regenerate" (see module docstring) — the only
    edge in `_MESSAGE_TRANSITIONS` that targets it. This function performs
    the two attribute-only obligations that implies: nulls `gmail_draft_id`
    (never let it point at a draft the caller is about to delete) and
    bumps `template_variant` (a message worth re-drafting probably read
    wrong the first time). Deleting the old Gmail draft itself is the
    caller's job — this function has no Gmail API access."""
    current = OutreachMessageState(message.state)
    move = _Move("message", message.message_id, current.value, to.value)
    _check_legal(_MESSAGE_TRANSITIONS, move, current, to)  # type: ignore[arg-type]
    _check_campaign_active(move, to, _MESSAGE_REQUIRES_ACTIVE_CAMPAIGN, campaign_status)

    message.state = to.value
    message.state_reason = reason
    now = datetime.now(UTC)
    message.state_changed_at = now
    if to == OutreachMessageState.DRAFTED:
        message.drafted_at = now
        message.gmail_draft_id = None
        message.template_variant += 1
    elif to == OutreachMessageState.SENT:
        message.sent_at = now
    elif to == OutreachMessageState.REPLIED:
        message.replied_at = now
    logger.info(
        "message_transition",
        extra={"message_id": str(message.message_id), "from": current.value, "to": to.value},
    )


def transition_campaign(
    campaign: OutreachCampaignRecord,
    to: OutreachCampaignStatus,
    *,
    reason: str | None,
) -> None:
    """No `campaign_status` gate parameter here (unlike the other three) —
    a campaign obviously can't be gated on its own status; that would be
    circular. `outreach_campaigns` has no `state_reason`/`state_changed_at`
    column (§11) — only `created_at` — so `reason` is logged (this
    module's "every transition logs" rule) but has nowhere to persist,
    the same category of gap `outreach_messages` had before v3.7. Not
    fixed here: no Stage 2 code path actually needs to explain *why* a
    campaign changed status (an operator clicking pause/resume needs no
    justification), unlike a domain or message failing on its own."""
    current = OutreachCampaignStatus(campaign.status)
    move = _Move("campaign", campaign.campaign_id, current.value, to.value)
    _check_legal(_CAMPAIGN_TRANSITIONS, move, current, to)  # type: ignore[arg-type]

    campaign.status = to.value
    logger.info(
        "campaign_transition",
        extra={"campaign_id": str(campaign.campaign_id), "from": current.value, "to": to.value},
    )
    if reason is not None:
        logger.info(
            "campaign_transition_reason",
            extra={"campaign_id": str(campaign.campaign_id), "reason": reason},
        )
