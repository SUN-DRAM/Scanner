import { describe, expect, it } from "vitest";

import { formatDateTimeDisplay, formatDateTimeDisplayIst } from "@/lib/format";

// Node's bundled ICU data abbreviates September as "Sept" for en-GB in this
// environment (browsers commonly render "Sep") — pre-existing, unrelated to
// this change, and shared by formatDateTimeDisplay's UTC formatter too.
// Match the day/year/time/IST-offset shape rather than hardcoding the month
// spelling, so this test isn't coupled to that ICU quirk.
const IST_SHAPE = /^\d{1,2} \w+ \d{4}, \d{2}:\d{2} IST \(UTC\+05:30\)$/;

describe("formatDateTimeDisplayIst (docs/Fix headers and incomplete.md §5)", () => {
  it("shifts a UTC timestamp to IST and names the offset", () => {
    // 09:00 UTC -> 14:30 IST (UTC+05:30).
    const result = formatDateTimeDisplayIst("2026-09-08T09:00:00Z");
    expect(result).toMatch(IST_SHAPE);
    expect(result).toContain("8 Sep");
    expect(result).toContain("2026, 14:30 IST (UTC+05:30)");
  });

  it("rolls over to the next calendar day when IST crosses midnight", () => {
    // 19:00 UTC on the 8th -> 00:30 IST on the 9th.
    const result = formatDateTimeDisplayIst("2026-09-08T19:00:00Z");
    expect(result).toMatch(IST_SHAPE);
    expect(result).toContain("9 Sep");
    expect(result).toContain("2026, 00:30 IST (UTC+05:30)");
  });

  it("matches app/pdf/template.py's _format_datetime_ist format exactly", () => {
    // Same worked example CONTRACT.md/PDF_FIXES.md use elsewhere in this
    // codebase — day/time/offset must line up with "15:30 IST (UTC+05:30)".
    const result = formatDateTimeDisplayIst("2026-09-12T10:00:00Z");
    expect(result).toMatch(IST_SHAPE);
    expect(result).toContain("12 Sep");
    expect(result).toContain("2026, 15:30 IST (UTC+05:30)");
  });

  it("is distinct from the UTC formatter it's replacing on the scan result page", () => {
    const iso = "2026-09-08T09:00:00Z";
    expect(formatDateTimeDisplay(iso)).toContain("09:00 UTC");
    expect(formatDateTimeDisplayIst(iso)).not.toBe(formatDateTimeDisplay(iso));
  });
});
