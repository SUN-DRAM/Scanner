"""Builds the report HTML from an already-completed `Scan` (contract §7.14).

Non-negotiable content rules (Step 2 of docs/FEATURE_PDF_EXPORT.md), enforced
structurally rather than by convention: every `title`/`description`/
`remediation`/`summary`/`headline` string is read verbatim off the `Scan`
object and passed through `_esc` (HTML-escaping only) — nothing here
rewrites, re-tones, or summarises scan content, and no grade, score,
severity, or count is ever recomputed; each is read from `scan` directly.
Section headings ("Executive summary", "Findings", …) are this module's own
UI chrome, the same kind of label `ScanResultBody.tsx` already writes for the
web report — not scan content, so the "verbatim" rule doesn't apply to them.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.enums import ModuleName
from app.pdf.fonts import logo_available
from app.schemas import CertificateData, Finding, ModuleResult, ReadinessData, Scan

_IST = ZoneInfo("Asia/Kolkata")

_THRESHOLD_ISO = "2027-03-15T00:00:00+00:00"
_THRESHOLD_LABEL = "15 Mar 2027"

# Mirrors ScanResultBody.tsx's MODULE_ORDER exactly — the PDF and the web
# report must present modules in the same order, per the "PDF content
# matches the web report exactly" test requirement.
_MODULE_ORDER: tuple[ModuleName, ...] = (
    ModuleName.CERTIFICATE,
    ModuleName.CHAIN,
    ModuleName.TLS,
    ModuleName.DNS,
    ModuleName.EMAIL_AUTH,
    ModuleName.HEADERS,
    ModuleName.READINESS,
)

_SEVERITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}

# Contract §12: "A+, A -> pass; B, C -> warn; D, E, F -> alert." Fixed, not
# computed — the same table lib/format.ts's gradeTone() encodes.
_GRADE_TONE = {
    "A+": "pass",
    "A": "pass",
    "B": "warn",
    "C": "warn",
    "D": "alert",
    "E": "alert",
    "F": "alert",
}

_SEVERITY_TONE = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
}


def _esc(value: object | None) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _format_date(dt: datetime) -> str:
    """Mirrors lib/format.ts's formatDateDisplay: "21 Aug 2026", UTC. Builds
    the day number manually rather than strftime's `%-d`/`%e`, which aren't
    portable across platforms (glibc vs. the Windows C runtime)."""
    return f"{dt.day} {dt.strftime('%b %Y')}"


def _format_datetime_ist(dt: datetime) -> str:
    """Cover timestamp, per Step 2: "scan timestamp in IST with UTC offset"
    — deliberately IST, not UTC like the web report, since this document's
    audience is the IST-based outreach list it's attached to."""
    local = dt.astimezone(_IST)
    return f"{local.day} {local.strftime('%b %Y, %H:%M')} IST (UTC+05:30)"


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def _docs_url(docs_path: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}{docs_path}"


def _grade_row_html(
    grade: str | None, score: int | None, size_class: str, cap_reason: str | None = None
) -> str:
    # §9 Step 4b (v3.0): `grade`/`score` are null exactly when `certificate`
    # didn't complete — "Incomplete", never a letter and never blank space
    # where a letter would have been, in the neutral/muted tone (not
    # "alert"), since this isn't a failing grade, it's the absence of one.
    if grade is None:
        return (
            f'<div class="{size_class}">'
            '<span class="grade-dial grade-incomplete">Incomplete</span>'
            "</div>"
        )
    tone = _GRADE_TONE.get(grade, "alert")
    score_html = f'<span class="cover-score">Score {score}/100</span>' if score is not None else ""
    # §9 Step 4 (v3.1): the letter and the score can legitimately disagree
    # (a critical finding or 2+ highs cap the letter below its own band) —
    # shown right under the dial so a reader never has to reconcile "C ·
    # Score 82/100" (a B) unaided.
    cap_reason_html = (
        f'<div class="grade-cap-reason">{_esc(grade)} — {_esc(cap_reason)}</div>'
        if cap_reason
        else ""
    )
    return (
        f'<div class="{size_class}">'
        f'<span class="grade-dial grade-{tone}">{_esc(grade)}</span>'
        f"{score_html}"
        f"{cap_reason_html}"
        f"</div>"
    )


def _incomplete_banner_html(scan: Scan) -> str:
    if scan.is_complete is not False:
        return ""
    count = len(scan.incomplete_modules or [])
    return (
        '<div class="incomplete-banner">'
        f"<strong>{count} of 7 checks did not complete.</strong> "
        "This assessment is partial and should not be treated as a clean result."
        "</div>"
    )


def _cover_html(scan: Scan) -> str:
    logo_html = (
        '<img class="cover-logo" src="assets/logo.svg" alt="SUN-DRAM logo" />'
        if logo_available()
        else ""
    )
    scanned_at = scan.completed_at or scan.created_at
    headline_html = f'<p class="cover-headline">{_esc(scan.headline)}</p>' if scan.headline else ""

    return f"""
<section class="cover">
  {logo_html}
  <h1 class="cover-wordmark display">SUN-DRAM</h1>
  <p class="cover-subtitle">External Security Assessment</p>
  <p class="cover-hostname mono">{_esc(scan.hostname)}</p>
  <p class="cover-timestamp mono">Scanned {_format_datetime_ist(scanned_at)}</p>
  <div class="cover-grade-row">
    {_grade_row_html(scan.overall_grade, scan.overall_score, "cover-grade", scan.grade_cap_reason)}
  </div>
  {headline_html}
  <p class="cover-disclaimer">
    This is an external, unauthenticated assessment of {_esc(scan.hostname)} —
    a single hostname, checked over the public internet from the outside,
    with no access granted and no manual review involved.
  </p>
</section>
"""


def _counts_row_html(scan: Scan) -> str:
    if scan.counts is None:
        return ""
    counts = scan.counts
    chips: list[str] = []
    for key, label in (
        ("critical", "Critical"),
        ("high", "High"),
        ("medium", "Medium"),
        ("low", "Low"),
        ("info", "Info"),
    ):
        value = getattr(counts, key)
        chips.append(
            f'<span class="count-chip count-{key}">'
            f'<span class="count-value">{value}</span> {label}'
            f"</span>"
        )
    return f'<div class="counts-row">{"".join(chips)}</div>'


def _modules_table_html(scan: Scan) -> str:
    rows: list[str] = []
    for name in _MODULE_ORDER:
        result: ModuleResult[Any] | None = getattr(scan.modules, name.value)
        label = result.label if result is not None else name.value.replace("_", " ").title()
        grade = result.grade if result is not None else None
        summary = result.summary if result is not None else "Not available for this scan."
        tone = _GRADE_TONE.get(grade or "")
        grade_html = (
            f'<span class="module-grade grade-{tone}">{_esc(grade)}</span>'
            if grade is not None
            else '<span class="muted">—</span>'
        )
        rows.append(
            f"<tr><td>{_esc(label)}</td><td>{grade_html}</td><td>{_esc(summary)}</td></tr>"
        )
    return f"""
<table class="modules-table">
  <thead><tr><th>Module</th><th>Grade</th><th>Summary</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _executive_summary_html(scan: Scan) -> str:
    grade_row = _grade_row_html(
        scan.overall_grade, scan.overall_score, "summary-grade", scan.grade_cap_reason
    )
    return f"""
<section class="section">
  <h2 class="section-title">Executive summary</h2>
  <div class="summary-grade-row">
    {grade_row}
  </div>
  {_counts_row_html(scan)}
  {_incomplete_banner_html(scan)}
  {_modules_table_html(scan)}
</section>
"""


def _validity_bar_html(
    cert_data: CertificateData, readiness_data: ReadinessData | None, now: datetime
) -> str:
    start = cert_data.not_before
    end = cert_data.not_after
    span_seconds = (end - start).total_seconds()
    if span_seconds <= 0:
        today_percent = 0.0
    else:
        today_percent = _clamp_percent(((now - start).total_seconds() / span_seconds) * 100)

    threshold = datetime.fromisoformat(_THRESHOLD_ISO)
    threshold_within_window = start <= threshold <= end
    threshold_percent = None
    if threshold_within_window and span_seconds > 0:
        threshold_seconds = (threshold - start).total_seconds()
        threshold_percent = _clamp_percent((threshold_seconds / span_seconds) * 100)

    threshold_marker_html = (
        f'<div class="validity-marker validity-marker-threshold" '
        f'style="left: {threshold_percent:.2f}%;"></div>'
        if threshold_percent is not None
        else ""
    )

    if threshold_percent is not None:
        threshold_legend = (
            f'<span><span class="legend-dot legend-dot-threshold"></span>'
            f"{_THRESHOLD_LABEL} deadline</span>"
        )
    elif readiness_data is not None and readiness_data.survives_2027 is not None:
        threshold_legend = (
            f"<span>This certificate's window ends before the {_THRESHOLD_LABEL} deadline.</span>"
            if readiness_data.survives_2027
            else (
                f"<span>This certificate's window extends past the "
                f"{_THRESHOLD_LABEL} deadline.</span>"
            )
        )
    else:
        threshold_legend = ""

    return f"""
<div class="validity-bar-track">
  <div class="validity-bar-fill" style="width: {today_percent:.2f}%;"></div>
  <div class="validity-marker validity-marker-today" style="left: {today_percent:.2f}%;"></div>
  {threshold_marker_html}
</div>
<div class="validity-dates-row mono">
  <span>{_format_date(start)}</span>
  <span>{_format_date(end)}</span>
</div>
<div class="validity-legend">
  <span><span class="legend-dot legend-dot-today"></span>Today</span>
  {threshold_legend}
</div>
<div class="validity-stats">
  <div>
    <div class="validity-stat-label">Days remaining</div>
    <div class="validity-stat-value">{cert_data.days_until_expiry}</div>
  </div>
  <div>
    <div class="validity-stat-label">Certificate lifetime</div>
    <div class="validity-stat-value">{cert_data.lifetime_days} days</div>
  </div>
</div>
"""


def _certificate_validity_section_html(scan: Scan) -> str:
    certificate = scan.modules.certificate
    if certificate is None or certificate.data is None:
        return ""
    scanned_at = scan.completed_at or scan.created_at
    readiness_data = scan.modules.readiness.data if scan.modules.readiness is not None else None
    return f"""
<section class="section">
  <h2 class="section-title">Certificate validity</h2>
  {_validity_bar_html(certificate.data, readiness_data, scanned_at)}
</section>
"""


def _readiness_section_html(scan: Scan) -> str:
    readiness = scan.modules.readiness
    if readiness is None or readiness.data is None:
        return """
<section class="section">
  <h2 class="section-title">CA/Browser Forum readiness</h2>
  <p class="muted">Not available for this scan.</p>
</section>
"""
    data = readiness.data

    def _renewal_cell(value: int | None) -> str:
        return str(value) if value is not None else "—"

    return f"""
<section class="section">
  <h2 class="section-title">CA/Browser Forum readiness</h2>
  <p class="readiness-verdict display">{_esc(data.verdict_label)}</p>
  <p class="readiness-reason">{_esc(data.verdict_reason)}</p>
  <table class="renewals-table mono">
    <thead><tr><th>Now</th><th>From Mar 2027</th><th>From Mar 2029</th></tr></thead>
    <tbody>
      <tr>
        <td class="renewals-value">{_renewal_cell(data.renewals_per_year_now)}/yr</td>
        <td class="renewals-value">{_renewal_cell(data.renewals_per_year_2027)}/yr</td>
        <td class="renewals-value">{_renewal_cell(data.renewals_per_year_2029)}/yr</td>
      </tr>
    </tbody>
  </table>
  <p class="readiness-countdown mono">{_esc(data.phase_label)} —
  {data.days_until_next_deadline} days until {_esc(data.next_deadline)}</p>
  <p>{_esc(data.message)}</p>
</section>
"""


def _finding_html(finding: Finding) -> str:
    tone = _SEVERITY_TONE.get(finding.severity, "info")
    label = _SEVERITY_LABELS.get(finding.severity, finding.severity)
    evidence_items = ", ".join(f"{_esc(k)}: {_esc(v)}" for k, v in finding.evidence.items())
    evidence_html = (
        f'<p class="finding-evidence mono">{evidence_items}</p>' if evidence_items else ""
    )
    docs_url = _esc(_docs_url(finding.docs_path))
    return f"""
<div class="finding">
  <div class="finding-header">
    <span class="severity-badge severity-{tone}">{_esc(label)}</span>
    <span class="finding-title">{_esc(finding.title)}</span>
  </div>
  <p class="finding-module mono">{_esc(finding.module)}</p>
  <p class="finding-description">{_esc(finding.description)}</p>
  <div class="finding-remediation">
    <div class="finding-remediation-label">Remediation</div>
    <div>{_esc(finding.remediation)}</div>
  </div>
  {evidence_html}
  <p class="finding-docs-link"><a href="{docs_url}">{docs_url}</a></p>
</div>
"""


def _findings_section_html(scan: Scan) -> str:
    if not scan.findings:
        return """
<section class="section">
  <h2 class="section-title">Findings</h2>
  <div class="clean-scan-banner">
    <span class="badge-pass">Clean result</span>
    <span>No findings on this scan. Nothing to fix.</span>
  </div>
</section>
"""
    # scan.findings is already sorted by severity then module (contract
    # §6.1) — grouped here for a heading per band, never re-sorted.
    finding_blocks: list[str] = []
    current_severity: str | None = None
    for finding in scan.findings:
        if finding.severity != current_severity:
            current_severity = finding.severity
            label = _SEVERITY_LABELS.get(current_severity, current_severity)
            count = getattr(scan.counts, current_severity) if scan.counts is not None else None
            count_suffix = f" ({count})" if count is not None else ""
            heading = f"{_esc(label)}{count_suffix}"
            finding_blocks.append(f'<h3 class="finding-group-heading">{heading}</h3>')
        finding_blocks.append(_finding_html(finding))

    return f"""
<section class="section">
  <h2 class="section-title">Findings ({len(scan.findings)})</h2>
  {"".join(finding_blocks)}
</section>
"""


def render_html(scan: Scan) -> str:
    """The full report document — cover, executive summary, certificate
    validity, readiness, and findings, in that order (Step 2's structure)."""
    from app.pdf.styles import full_stylesheet

    body = "\n".join(
        [
            _cover_html(scan),
            _executive_summary_html(scan),
            _certificate_validity_section_html(scan),
            _readiness_section_html(scan),
            _findings_section_html(scan),
        ]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>SUN-DRAM security report — {_esc(scan.hostname)}</title>
<style>{full_stylesheet()}</style>
</head>
<body>
{body}
</body>
</html>
"""
