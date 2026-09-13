"""Report filename (contract §7.14, v2.9): `SUN-DRAM-Security-Report-{hostname}-{YYYY-MM-DD}.pdf`.

Date is the scan's `completed_at` converted to IST — this is the one place
in the PDF export path a UTC timestamp is deliberately shown in a different
zone, because §7.2 already normalises every stored hostname to ASCII
punycode (`[a-z0-9.-]`), so it needs no further sanitisation to be a safe
filename — but that is asserted here defensively, in code and in a test,
rather than assumed.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

# §7.2 step 6 already restricts a stored hostname to this exact character
# set (lowercase ascii/digits/hyphens/dots). Anything else surviving to here
# would mean normalisation was bypassed somewhere upstream — stripped, not
# trusted, so a stray character can never reach a Content-Disposition header.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^a-z0-9.-]")


def sanitize_hostname_for_filename(hostname: str) -> str:
    """Defends the filename even if an unexpected character somehow reaches
    here — never assumes §7.2's guarantee holds without checking."""
    return _UNSAFE_FILENAME_CHARS.sub("", hostname.lower())


def build_report_filename(hostname: str, completed_at: datetime) -> str:
    """`completed_at` must be timezone-aware (contract rule 6: never naive)."""
    if completed_at.tzinfo is None:
        raise ValueError("completed_at must be timezone-aware")

    safe_hostname = sanitize_hostname_for_filename(hostname)
    date_ist = completed_at.astimezone(_IST).strftime("%Y-%m-%d")
    return f"SUN-DRAM-Security-Report-{safe_hostname}-{date_ist}.pdf"
