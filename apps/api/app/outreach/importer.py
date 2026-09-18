"""CSV import (contract §7.15, spec §17). Implements §17.4 exactly:
column-order-independent parsing, contact_email-grouped prospects, §7.2/§10
hostname validation reused directly (no parallel path), suppression
checked at import, and full idempotency — importing the same file twice
must create zero new rows.

File-level vs. row-level failure (a decision the spec leaves implicit, made
and documented here per CONTRACT.md §7.15): not valid UTF-8, no header
row, zero data rows, or more data rows than `OUTREACH_MAX_IMPORT_ROWS`
each abort the whole import via `ApiException(VALIDATION_ERROR)` before any
row is touched. Everything else §17.4 calls "reject and report" — one bad
hostname, one missing column, one suppressed email, one duplicate row — is
a row-level outcome: the import still runs, and that row surfaces in the
returned `ImportReport` instead.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import OutreachDomainState, OutreachProspectState
from app.errors import ApiException, ErrorCode
from app.models import (
    OutreachCampaignRecord,
    OutreachDomainRecord,
    OutreachProspectRecord,
    OutreachSuppressionRecord,
)
from app.safety import (
    HostnameResolutionError,
    normalize_hostname,
    resolve_and_validate,
    validate_port,
)

REQUIRED_COLUMNS: tuple[str, ...] = ("agency_name", "contact_email", "client_domain")

# §17.2 CSV enums — Python-level closed sets, not promoted to contract §5
# (see app/models.py's OutreachProspectRecord docstring): nothing outside
# this importer reads either one yet.
ALLOWED_SOURCES: frozenset[str] = frozenset(
    {"clutch", "goodfirms", "designrush", "sortlist", "manifest", "linkedin", "google", "other"}
)
ALLOWED_ICP_GRADES: frozenset[str] = frozenset({"strong", "potential", "weak"})

# §17.2: "Never info@ or contact@" — a generic mailbox isn't a real contact
# identity, and is disproportionately likely to be a shared/monitored inbox
# a cold email shouldn't reach.
_GENERIC_EMAIL_LOCAL_PARTS: frozenset[str] = frozenset({"info", "contact"})
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class RejectedRow:
    row_number: int
    reason: str


@dataclass
class ImportWarning:
    contact_email: str
    message: str


@dataclass
class ImportReport:
    """Field names match contract §7.15's `OutreachImportReport` exactly —
    Stage 1's admin router (Step 5) wraps this dataclass in the Pydantic
    schema of the same shape without renaming anything."""

    imported_agencies: int
    imported_domains: int
    skipped_agencies: int
    suppressed_agencies: int
    rejected_rows: list[RejectedRow]
    warnings: list[ImportWarning]


@dataclass
class _ValidRow:
    contact_email: str
    agency_name: str
    contact_name: str | None
    notes: str | None
    source: str | None
    icp_grade: str | None
    client_hostname: str
    own_hostname: str | None


@dataclass
class _Group:
    agency_name: str
    contact_name: str | None
    notes: str | None
    source: str | None
    icp_grade: str | None
    own_hostname: str | None
    client_hostnames: list[str] = field(default_factory=list)
    warned_name_diff: bool = False


def _file_error(message: str, **details: object) -> ApiException:
    return ApiException(ErrorCode.VALIDATION_ERROR, message, details or None)


def _decode(csv_bytes: bytes) -> str:
    try:
        return csv_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _file_error("The CSV file is not valid UTF-8.") from exc


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _validate_hostname(
    raw: str, cache: dict[str, ApiException | None]
) -> tuple[str | None, ApiException | None]:
    """Reuses §7.2 normalisation and the §10 safety guard directly — the
    same two calls `app/admin/prospects.py`'s batch scanner makes, no
    parallel path. A hostname that simply doesn't resolve is *not*
    rejected — same treatment a public scan gets (§7.4); it just never
    gets a `scan_id` once Stage 2 tries to scan it."""
    try:
        normalized = normalize_hostname(raw, None)
        validate_port(normalized.port)
    except ApiException as exc:
        return None, exc

    if normalized.hostname not in cache:
        try:
            await resolve_and_validate(normalized.hostname)
            cache[normalized.hostname] = None
        except ApiException as exc:
            cache[normalized.hostname] = exc
        except HostnameResolutionError:
            cache[normalized.hostname] = None

    blocked = cache[normalized.hostname]
    if blocked is not None:
        return None, blocked
    return normalized.hostname, None


async def import_csv(
    session: AsyncSession, *, campaign_id: uuid.UUID, csv_bytes: bytes
) -> ImportReport:
    campaign = await session.get(OutreachCampaignRecord, campaign_id)
    if campaign is None:
        raise ApiException(
            ErrorCode.NOT_FOUND,
            "No outreach campaign found.",
            {"campaign_id": str(campaign_id)},
        )

    text = _decode(csv_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise _file_error("The CSV file has no header row.")

    missing_columns = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing_columns:
        raise _file_error(
            f"The CSV is missing required column(s): {', '.join(missing_columns)}.",
            missing_columns=missing_columns,
        )

    raw_rows = list(reader)
    if not raw_rows:
        raise _file_error("The CSV has no data rows.")

    max_rows = get_settings().outreach_max_import_rows
    if len(raw_rows) > max_rows:
        raise _file_error(
            f"The CSV has {len(raw_rows)} data rows, over the {max_rows}-row limit.",
            row_count=len(raw_rows),
            max_rows=max_rows,
        )

    rejected_rows: list[RejectedRow] = []
    warnings: list[ImportWarning] = []
    hostname_cache: dict[str, ApiException | None] = {}
    groups: dict[str, _Group] = {}

    for row_number, row in enumerate(raw_rows, start=1):
        reason = _validate_required_columns(row)
        if reason is not None:
            rejected_rows.append(RejectedRow(row_number, reason))
            continue

        contact_email = row["contact_email"].strip().lower()
        reason = _validate_contact_email(contact_email)
        if reason is not None:
            rejected_rows.append(RejectedRow(row_number, reason))
            continue

        icp_grade = _clean(row.get("icp_grade"))
        if icp_grade is not None:
            icp_grade = icp_grade.lower()
            if icp_grade not in ALLOWED_ICP_GRADES:
                rejected_rows.append(RejectedRow(row_number, f"invalid icp_grade: {icp_grade}"))
                continue

        source = _clean(row.get("source"))
        if source is not None:
            source = source.lower()
            if source not in ALLOWED_SOURCES:
                rejected_rows.append(RejectedRow(row_number, f"invalid source: {source}"))
                continue

        client_hostname, error = await _validate_hostname(row["client_domain"], hostname_cache)
        if error is not None:
            rejected_rows.append(RejectedRow(row_number, f"invalid client_domain: {error.message}"))
            continue

        own_hostname: str | None = None
        raw_website = _clean(row.get("agency_website"))
        if raw_website is not None:
            own_hostname, website_error = await _validate_hostname(raw_website, hostname_cache)
            if website_error is not None:
                # agency_website is optional (§17.2) — a bad value drops
                # just that one domain, not the whole row (client_domain,
                # the row's required subject, is unaffected).
                warnings.append(
                    ImportWarning(
                        contact_email,
                        f"agency_website '{raw_website}' invalid: "
                        f"{website_error.message}. Dropped.",
                    )
                )

        valid = _ValidRow(
            contact_email=contact_email,
            agency_name=row["agency_name"].strip(),
            contact_name=_clean(row.get("contact_name")),
            notes=_clean(row.get("notes")),
            source=source,
            icp_grade=icp_grade,
            client_hostname=client_hostname,  # type: ignore[arg-type]
            own_hostname=own_hostname,
        )
        _add_to_group(groups, valid, warnings)

    if not groups:
        return ImportReport(0, 0, 0, 0, rejected_rows, warnings)

    suppressed = set(
        (
            await session.execute(
                select(OutreachSuppressionRecord.email).where(
                    OutreachSuppressionRecord.email.in_(groups.keys())
                )
            )
        )
        .scalars()
        .all()
    )

    imported_agencies = 0
    imported_domains = 0
    skipped_agencies = 0
    suppressed_agencies = 0

    for email, group in groups.items():
        if email in suppressed:
            suppressed_agencies += 1
            continue

        prospect = await session.scalar(
            select(OutreachProspectRecord).where(
                OutreachProspectRecord.campaign_id == campaign_id,
                OutreachProspectRecord.contact_email == email,
            )
        )
        if prospect is None:
            prospect = OutreachProspectRecord(
                prospect_id=uuid.uuid4(),
                campaign_id=campaign_id,
                agency_name=group.agency_name,
                agency_website=group.own_hostname,
                contact_name=group.contact_name,
                contact_email=email,
                source=group.source,
                icp_grade=group.icp_grade,
                state=OutreachProspectState.PENDING.value,
                notes=group.notes,
            )
            session.add(prospect)
            imported_agencies += 1
        else:
            # Already in this campaign — counted as skipped (§17.5), but its
            # domains are still processed below: (prospect_id, hostname) is
            # its own independent dedup key (§17.4.4), so a re-import that
            # adds a genuinely new client_domain for an existing agency
            # still gets it, rather than the agency-level skip silently
            # swallowing it. A byte-for-byte repeat import — the literal
            # idempotency case — finds no new hostnames here either way.
            skipped_agencies += 1

        existing_hostnames = set(
            (
                await session.execute(
                    select(OutreachDomainRecord.hostname).where(
                        OutreachDomainRecord.prospect_id == prospect.prospect_id
                    )
                )
            )
            .scalars()
            .all()
        )

        unique_client_hostnames = dict.fromkeys(group.client_hostnames)
        wanted: list[tuple[str, str]] = [(h, "client") for h in unique_client_hostnames]
        if group.own_hostname is not None:
            wanted.append((group.own_hostname, "own"))

        for hostname, relationship in wanted:
            if hostname in existing_hostnames:
                continue
            session.add(
                OutreachDomainRecord(
                    domain_id=uuid.uuid4(),
                    prospect_id=prospect.prospect_id,
                    hostname=hostname,
                    relationship_=relationship,
                    state=OutreachDomainState.PENDING.value,
                )
            )
            existing_hostnames.add(hostname)
            imported_domains += 1

        await session.commit()

    return ImportReport(
        imported_agencies=imported_agencies,
        imported_domains=imported_domains,
        skipped_agencies=skipped_agencies,
        suppressed_agencies=suppressed_agencies,
        rejected_rows=rejected_rows,
        warnings=warnings,
    )


def _validate_required_columns(row: dict[str, str | None]) -> str | None:
    for column in REQUIRED_COLUMNS:
        if not (row.get(column) or "").strip():
            return f"missing {column}"
    return None


def _validate_contact_email(contact_email: str) -> str | None:
    if not _EMAIL_RE.match(contact_email):
        return f"invalid contact_email: {contact_email}"
    local_part = contact_email.split("@", 1)[0]
    if local_part in _GENERIC_EMAIL_LOCAL_PARTS:
        return f"generic contact_email not allowed: {contact_email}"
    return None


def _add_to_group(
    groups: dict[str, _Group], row: _ValidRow, warnings: list[ImportWarning]
) -> None:
    group = groups.get(row.contact_email)
    if group is None:
        group = _Group(
            agency_name=row.agency_name,
            contact_name=row.contact_name,
            notes=row.notes,
            source=row.source,
            icp_grade=row.icp_grade,
            own_hostname=row.own_hostname,
        )
        groups[row.contact_email] = group
    else:
        if row.agency_name != group.agency_name and not group.warned_name_diff:
            warnings.append(
                ImportWarning(
                    row.contact_email,
                    "agency_name differs across rows for this email; used the first value",
                )
            )
            group.warned_name_diff = True
        group.contact_name = group.contact_name or row.contact_name
        group.notes = group.notes or row.notes
        group.source = group.source or row.source
        group.icp_grade = group.icp_grade or row.icp_grade
        group.own_hostname = group.own_hostname or row.own_hostname

    group.client_hostnames.append(row.client_hostname)
