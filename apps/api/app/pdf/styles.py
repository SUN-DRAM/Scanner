"""CSS for the PDF report — contract §12 tokens reused verbatim as CSS custom
properties (Step 1 decision 1.2's whole reason for picking WeasyPrint: "the
§12 tokens are reused literally as CSS custom properties rather than
re-expressed imperatively in Python").

One deliberate, documented exception to §12: the cover logo (`assets/logo.svg`,
provided by the human) keeps its own gold colouring rather than being
recoloured onto the ink/cobalt palette — a human decision made explicitly for
this asset, in this session, not a silent drift from the design system.
Nothing else in this stylesheet uses that colour.
"""

from __future__ import annotations

from app.pdf.fonts import font_face_css

TOKENS_CSS = """
:root {
  --ink: #0B1B2B;
  --ink-muted: #5A6B7C;
  --paper: #F6F8FA;
  --surface: #FFFFFF;
  --line: #E3E8ED;
  --cobalt: #1B4DFF;
  --cobalt-soft: #E9EEFF;
  --pass: #0E9F6E;
  --warn: #E4A11B;
  --alert: #D7263D;
}
"""

PAGE_CSS = """
@page {
  size: A4;
  margin: 20mm 18mm 24mm 18mm;

  @bottom-center {
    content: "SUN-DRAM · Infrastructure security monitoring · sundram.tech · page "
      counter(page) " of " counter(pages);
    font-family: "Inter", sans-serif;
    font-size: 8pt;
    color: #5A6B7C;
    padding-top: 6mm;
  }
}

@page cover {
  @bottom-center { content: none; }
}
"""

BASE_CSS = """
* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  color: var(--ink);
  background: var(--surface);
  font-family: "Inter", sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
}

h1, h2, h3, .display {
  font-family: "Space Grotesk", sans-serif;
  line-height: 1.2;
  font-weight: 700;
  color: var(--ink);
  margin: 0;
}

.mono {
  font-family: "JetBrains Mono", monospace;
}

a { color: var(--cobalt); text-decoration: none; }

.section {
  /* Deliberately no break-inside: avoid-page here — a whole section (e.g.
     a long Findings list) forced onto one page would either overflow or,
     worse, get pushed entirely to the next page leaving the current one's
     remaining space blank, exactly the "no large blank pages" rule Step 2
     forbids. Only .finding (below) — a single, genuinely atomic block —
     gets that treatment. */
  padding: 10mm 0;
  border-bottom: 1px solid var(--line);
}
.section:last-child { border-bottom: none; }

.section-title {
  font-size: 14pt;
  margin-bottom: 5mm;
}

.muted { color: var(--ink-muted); }

/* --- Cover (page 1) --- */

.cover {
  page: cover;
  height: 249mm; /* A4 minus this page's own margins */
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 4mm;
}

.cover-logo {
  max-width: 32mm;
  max-height: 32mm;
  margin-bottom: 4mm;
  object-fit: contain;
}

.cover-wordmark {
  font-size: 22pt;
}

.cover-subtitle {
  font-size: 12pt;
  color: var(--ink-muted);
  margin-bottom: 6mm;
}

.cover-hostname {
  font-size: 16pt;
  padding: 2mm 6mm;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.cover-timestamp {
  font-size: 9pt;
  color: var(--ink-muted);
}

.cover-grade-row {
  display: flex;
  align-items: baseline;
  gap: 4mm;
  margin-top: 6mm;
}

.grade-dial {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  font-size: 40pt;
  line-height: 1;
}
.grade-pass { color: var(--pass); }
.grade-warn { color: var(--warn); }
.grade-alert { color: var(--alert); }
/* §9 Step 4b (v3.0): absence of a grade, not a failing one — deliberately
   not --alert, which would misread as "scored F". */
.grade-incomplete { color: var(--ink-muted); font-size: 22pt; }

.cover-score {
  font-size: 11pt;
  color: var(--ink-muted);
  margin-left: 3mm;
}

.cover-headline {
  max-width: 130mm;
  font-size: 12pt;
  margin-top: 4mm;
}

.cover-disclaimer {
  position: absolute;
  bottom: 12mm;
  max-width: 150mm;
  font-size: 8pt;
  color: var(--ink-muted);
}

/* --- Executive summary --- */

.summary-grade-row {
  display: flex;
  align-items: baseline;
  gap: 6mm;
  margin-bottom: 6mm;
}

.counts-row {
  display: flex;
  gap: 4mm;
  margin-bottom: 6mm;
  flex-wrap: wrap;
}

.count-chip {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 2mm 4mm;
  font-size: 9pt;
  display: flex;
  align-items: baseline;
  gap: 2mm;
}
.count-chip .count-value {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  font-size: 12pt;
}
.incomplete-banner {
  border: 1px solid var(--alert);
  background: rgba(215, 38, 61, 0.06);
  border-radius: 10px;
  padding: 4mm 5mm;
  margin-bottom: 6mm;
  font-size: 9.5pt;
}
.incomplete-banner strong { font-family: "Space Grotesk", sans-serif; }

.count-critical .count-value, .count-high .count-value { color: var(--alert); }
.count-medium .count-value { color: var(--warn); }
.count-low .count-value, .count-info .count-value { color: var(--ink-muted); }

table.modules-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 9.5pt;
}
table.modules-table th {
  text-align: left;
  font-family: "Space Grotesk", sans-serif;
  font-size: 8.5pt;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--ink-muted);
  border-bottom: 1px solid var(--line);
  padding: 2mm 3mm;
}
table.modules-table td {
  border-bottom: 1px solid var(--line);
  padding: 2.5mm 3mm;
  vertical-align: top;
}
table.modules-table tr:last-child td { border-bottom: none; }
.module-grade { font-family: "Space Grotesk", sans-serif; font-weight: 700; }

/* --- Validity bar --- */

.validity-bar-track {
  position: relative;
  height: 3mm;
  border-radius: 3mm;
  background: var(--line);
  margin: 6mm 0 3mm 0;
}
.validity-bar-fill {
  position: absolute;
  top: 0; left: 0;
  height: 3mm;
  border-radius: 3mm;
  background: var(--cobalt-soft);
}
.validity-marker {
  position: absolute;
  top: -1.5mm;
  width: 0.6mm;
  height: 6mm;
}
.validity-marker-today { background: var(--cobalt); }
.validity-marker-threshold { background: var(--alert); }

.validity-dates-row {
  display: flex;
  justify-content: space-between;
  font-size: 9pt;
}

.validity-legend {
  display: flex;
  gap: 6mm;
  margin-top: 3mm;
  font-size: 8.5pt;
  color: var(--ink-muted);
}
.legend-dot {
  display: inline-block;
  width: 2mm;
  height: 2mm;
  border-radius: 2mm;
  margin-right: 1.5mm;
}
.legend-dot-today { background: var(--cobalt); }
.legend-dot-threshold { background: var(--alert); }

.validity-stats {
  display: flex;
  gap: 10mm;
  margin-top: 6mm;
}
.validity-stat-label {
  font-size: 8.5pt;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.validity-stat-value {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  font-size: 13pt;
}

/* --- Readiness --- */

.readiness-verdict {
  font-size: 13pt;
  margin-bottom: 2mm;
}
.readiness-reason {
  margin-bottom: 5mm;
}
table.renewals-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 9.5pt;
  margin-bottom: 5mm;
}
table.renewals-table th, table.renewals-table td {
  border: 1px solid var(--line);
  padding: 2.5mm 3mm;
  text-align: center;
}
table.renewals-table th {
  background: var(--paper);
  font-family: "Space Grotesk", sans-serif;
  font-size: 8.5pt;
  text-transform: uppercase;
}
table.renewals-table td.renewals-value {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
}
.readiness-countdown {
  font-size: 10pt;
  color: var(--ink-muted);
}

/* --- Findings --- */

.finding {
  break-inside: avoid;
  padding: 4mm 0;
  border-bottom: 1px solid var(--line);
}
.finding:last-child { border-bottom: none; }

.finding-header {
  display: flex;
  align-items: baseline;
  gap: 3mm;
  margin-bottom: 2mm;
}
.finding-title {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  font-size: 11pt;
}
.severity-badge {
  font-size: 7.5pt;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.5mm 2mm;
  border-radius: 6px;
  font-family: "Inter", sans-serif;
  font-weight: 600;
}
.severity-critical, .severity-high {
  background: rgba(215, 38, 61, 0.1);
  color: var(--alert);
}
.severity-medium {
  background: rgba(228, 161, 27, 0.1);
  color: var(--warn);
}
.severity-low, .severity-info {
  background: rgba(90, 107, 124, 0.1);
  color: var(--ink-muted);
}
.finding-module {
  font-size: 8.5pt;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.finding-description { margin-bottom: 2mm; }
.finding-remediation {
  background: var(--paper);
  border-radius: 6px;
  padding: 3mm;
  margin-bottom: 2mm;
}
.finding-remediation-label {
  font-size: 8pt;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--ink-muted);
  margin-bottom: 1mm;
}
.finding-evidence {
  font-size: 8.5pt;
  color: var(--ink-muted);
}
.finding-docs-link {
  font-size: 8.5pt;
}

.clean-scan-banner {
  display: flex;
  align-items: center;
  gap: 4mm;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 6mm;
}
.clean-scan-banner .badge-pass {
  font-family: "Space Grotesk", sans-serif;
  font-weight: 700;
  color: var(--pass);
  font-size: 12pt;
}
"""


def full_stylesheet() -> str:
    return "\n".join([TOKENS_CSS, font_face_css(), PAGE_CSS, BASE_CSS])
