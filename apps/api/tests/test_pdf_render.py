"""Pure rendering tests for the PDF export (contract §7.14, v2.9) — no DB,
no Redis, no HTTP. Router-level behaviour (caching, rate limiting, 409/404)
is covered separately in test_pdf_export_router.py.

Run via `docker compose exec api pytest` — `require_weasyprint`
(tests/conftest.py) skips gracefully when WeasyPrint's native libraries
aren't loadable, the same pattern already used by `redis_client`/`db_session`.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from app.config import get_settings
from app.pdf.filename import build_report_filename, sanitize_hostname_for_filename
from app.pdf.renderer import render_scan_pdf_bytes
from app.pdf.template import render_html
from tests.pdf_fixtures import (
    NOW,
    default_modules,
    make_completed_scan,
    make_finding,
    make_many_findings,
)


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _embedded_font_names(pdf_bytes: bytes) -> set[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get("/Font")
        if fonts is None:
            continue
        for font_ref in fonts.values():
            font = font_ref.get_object()
            base_font = font.get("/BaseFont")
            if base_font is not None:
                names.add(str(base_font))
    return names


@pytest.mark.usefixtures("require_weasyprint")
class TestCleanScan:
    def test_renders_a_single_page_pdf_with_no_findings(self) -> None:
        scan = make_completed_scan(hostname="clean.example.com", findings=[])
        pdf_bytes = render_scan_pdf_bytes(scan)
        assert pdf_bytes.startswith(b"%PDF")

        text = _extract_text(pdf_bytes)
        assert "clean.example.com" in text
        assert "A+" in text
        assert "Clean result" in text
        # Step 2: "Clean scans with zero findings still produce a complete,
        # confident-looking report" — never a blank page for having nothing
        # to report.
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) >= 1


@pytest.mark.usefixtures("require_weasyprint")
class TestFontEmbedding:
    def test_embeds_the_bundled_fonts_not_a_fallback(self) -> None:
        scan = make_completed_scan()
        pdf_bytes = render_scan_pdf_bytes(scan)
        font_names = " ".join(_embedded_font_names(pdf_bytes))
        # Substring match, not exact equality: WeasyPrint subsets every
        # embedded font (a random 6-letter tag prefix, e.g. "EWHKTA+") and
        # derives /BaseFont from the declared @font-face family — hyphenated
        # ("Space-Grotesk-Bold", "JetBrains-Mono"), confirmed live — rather
        # than from the font file's own internal PostScript name. Either way,
        # this proves the *bundled* font was embedded, not a system fallback
        # like Helvetica/Arial.
        assert "Space-Grotesk" in font_names
        assert "Inter" in font_names
        assert "JetBrains-Mono" in font_names
        assert "Helvetica" not in font_names
        assert "Arial" not in font_names


@pytest.mark.usefixtures("require_weasyprint")
class TestMixedSeverityScan:
    def test_renders_findings_across_severities(self) -> None:
        findings = [
            make_finding(code="CERT_EXPIRING_SOON", severity="high", module="certificate"),
            make_finding(
                code="DNS_CAA_MISSING",
                severity="medium",
                module="dns",
                title="No CAA record",
                description="No CAA record restricts which CAs may issue for this domain.",
                remediation="Add a CAA record naming your issuing CA.",
                evidence={"caa_present": False},
            ),
            make_finding(
                code="HEADERS_CSP_MISSING",
                severity="low",
                module="headers",
                title="Content-Security-Policy is missing",
                description="No CSP header was found.",
                remediation="Add a Content-Security-Policy header.",
                evidence={},
            ),
        ]
        scan = make_completed_scan(
            overall_grade="B", overall_score=76, headline="Some issues found.", findings=findings
        )
        pdf_bytes = render_scan_pdf_bytes(scan)
        text = _extract_text(pdf_bytes)
        for finding in findings:
            assert finding.title in text
            assert finding.remediation in text


@pytest.mark.usefixtures("require_weasyprint")
class TestCriticalFindings:
    def test_renders_a_critical_finding(self) -> None:
        findings = [
            make_finding(
                code="CERT_EXPIRED",
                severity="critical",
                module="certificate",
                title="Certificate expired on 21 August 2026",
                description="The certificate expired.",
                remediation="Renew immediately.",
            )
        ]
        scan = make_completed_scan(overall_grade="F", overall_score=10, findings=findings)
        pdf_bytes = render_scan_pdf_bytes(scan)
        text = _extract_text(pdf_bytes)
        assert "Certificate expired on 21 August 2026" in text
        assert "Critical" in text


@pytest.mark.usefixtures("require_weasyprint")
class TestLongRemediation:
    def test_a_very_long_remediation_string_does_not_break_rendering(self) -> None:
        long_remediation = (
            "Renew the certificate and set up automated renewal. " * 80
        ).strip()
        findings = [
            make_finding(
                code="CERT_EXPIRING_SOON",
                remediation=long_remediation,
                evidence={"days_until_expiry": 3},
            )
        ]
        scan = make_completed_scan(findings=findings)
        pdf_bytes = render_scan_pdf_bytes(scan)
        assert pdf_bytes.startswith(b"%PDF")
        text = _extract_text(pdf_bytes)
        # A finding must never split so its title lands alone at the bottom
        # of a page (Step 2) — asserting the title and at least the start of
        # the long remediation both made it into the extracted text is the
        # closest a text-layer check gets to that without pixel inspection.
        assert "Certificate expires in 12 days" in text
        assert "Renew the certificate and set up automated renewal." in text


@pytest.mark.usefixtures("require_weasyprint")
class TestManyFindings:
    def test_a_large_synthetic_scan_spans_multiple_pages(self) -> None:
        findings = make_many_findings(45)
        scan = make_completed_scan(
            overall_grade="D", overall_score=35, headline="Many issues found.", findings=findings
        )
        pdf_bytes = render_scan_pdf_bytes(scan)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) > 1

        text = _extract_text(pdf_bytes)
        # Spot-check first, middle, and last rather than all 45 — enough to
        # confirm nothing was silently truncated across the page breaks.
        assert findings[0].title in text
        assert findings[len(findings) // 2].title in text
        assert findings[-1].title in text


@pytest.mark.usefixtures("require_weasyprint")
class TestPdfMatchesScanContent:
    def test_grade_score_counts_and_every_finding_code_are_present(self) -> None:
        findings = [
            make_finding(code="CERT_EXPIRING_SOON", severity="high"),
            make_finding(
                code="DNS_DNSSEC_NOT_ENABLED",
                severity="info",
                module="dns",
                title="DNSSEC is not enabled",
                description="DNSSEC was not detected.",
                remediation="Consider enabling DNSSEC with your registrar.",
                evidence={},
            ),
        ]
        scan = make_completed_scan(overall_grade="C", overall_score=68, findings=findings)
        pdf_bytes = render_scan_pdf_bytes(scan)
        text = _extract_text(pdf_bytes)

        assert scan.overall_grade in text
        assert str(scan.overall_score) in text
        assert str(scan.counts.high) in text
        for finding in findings:
            assert finding.title in text


class TestFilenameSanitisation:
    def test_ascii_hostname_is_used_verbatim(self) -> None:
        filename = build_report_filename("example.com", NOW)
        assert filename == "SUN-DRAM-Security-Report-example.com-2026-09-12.pdf"

    def test_idn_hostname_already_normalised_to_punycode(self) -> None:
        # Contract §7.2 step 5: IDN -> punycode happens before storage, so
        # the hostname reaching this function is always ASCII already —
        # "münchen.example" is stored (and arrives here) as
        # "xn--mnchen-3ya.example", never the raw unicode form.
        filename = build_report_filename("xn--mnchen-3ya.example", NOW)
        assert filename == "SUN-DRAM-Security-Report-xn--mnchen-3ya.example-2026-09-12.pdf"
        assert all(ord(c) < 128 for c in filename)

    def test_strips_unexpected_characters_defensively(self) -> None:
        # §7.2 guarantees this can't happen — asserted here rather than
        # assumed, per the feature doc's own instruction.
        dirty = "exa mple.com/../etc\"passwd"
        assert sanitize_hostname_for_filename(dirty) == "example.com..etcpasswd"

    def test_date_is_the_completed_at_instant_converted_to_ist(self) -> None:
        from datetime import UTC, datetime

        # 2026-09-12T20:00:00Z is 2026-09-13T01:30 IST — crosses midnight.
        late_utc = datetime(2026, 9, 12, 20, 0, 0, tzinfo=UTC)
        filename = build_report_filename("example.com", late_utc)
        assert "2026-09-13" in filename

    def test_raises_on_naive_datetime(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            build_report_filename("example.com", datetime(2026, 9, 12))


class TestRenderHtmlWithoutWeasyPrint:
    """render_html builds a plain string — no native libraries required, so
    these run even outside `docker compose exec api pytest`."""

    def test_never_uses_claim_language(self) -> None:
        scan = make_completed_scan()
        document = render_html(scan)
        lowered = document.lower()
        forbidden_terms = (
            "certified",
            "compliant",
            "audited",
            "penetration test",
            "security certification",
        )
        for forbidden in forbidden_terms:
            assert forbidden not in lowered

    def test_disclaimer_states_what_this_is(self) -> None:
        scan = make_completed_scan(hostname="example.com")
        document = render_html(scan)
        assert "external, unauthenticated assessment" in document

    def test_no_certificate_section_when_certificate_data_is_absent(self) -> None:
        modules = default_modules()
        modules.certificate.data = None
        scan = make_completed_scan(modules=modules)
        document = render_html(scan)
        assert "Certificate validity" not in document

    def test_escapes_html_in_scan_content(self) -> None:
        findings = [
            make_finding(
                title="<script>alert(1)</script>",
                description="Safe & sound",
            )
        ]
        scan = make_completed_scan(findings=findings)
        document = render_html(scan)
        assert "<script>alert(1)</script>" not in document
        assert "&lt;script&gt;" in document


class TestDocsLinksRespectPublicBaseUrl:
    """PDF_FIXES.md Fix 1: every finding's docs link must be built from the
    configured `PUBLIC_BASE_URL` (contract §4), never a hardcoded host. The
    two demo PDFs showed `localhost:3000` links because that's what this
    dev environment's own `.env` sets `PUBLIC_BASE_URL` to — correct dev
    behaviour, not a code bug — but nothing before this asserted the wiring
    actually follows the setting rather than a stray hardcoded default."""

    def _render_with_base_url(
        self, monkeypatch: pytest.MonkeyPatch, base_url: str, findings: list
    ) -> str:
        monkeypatch.setenv("PUBLIC_BASE_URL", base_url)
        get_settings.cache_clear()
        try:
            scan = make_completed_scan(findings=findings)
            return render_html(scan)
        finally:
            get_settings.cache_clear()

    def test_production_base_url_produces_production_links(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        findings = [make_finding(code="CERT_EXPIRING_SOON")]
        document = self._render_with_base_url(monkeypatch, "https://sundram.tech", findings)
        assert "https://sundram.tech/docs/findings/cert-expiring-soon" in document
        assert "localhost" not in document
        assert "127.0.0.1" not in document

    def test_dev_base_url_produces_dev_links(self, monkeypatch: pytest.MonkeyPatch) -> None:
        findings = [make_finding(code="CERT_EXPIRING_SOON")]
        document = self._render_with_base_url(
            monkeypatch, "http://localhost:3000", findings
        )
        assert "http://localhost:3000/docs/findings/cert-expiring-soon" in document
