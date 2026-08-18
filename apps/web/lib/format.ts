/**
 * Presentation-only helpers. Nothing here computes a grade, a severity, a
 * verdict, or a day count — those are backend facts (CLAUDE.md rule 3). This
 * file only reformats values the API already returned, or maps a *fixed*
 * design-system rule from contract §12 (e.g. "grade X is always tone Y")
 * onto Tailwind classes.
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { Currency, Grade, Severity } from "@/types/contract";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Contract §12: "A+, A -> pass; B, C -> warn; D, E, F -> alert." Fixed, not computed. */
export type Tone = "pass" | "warn" | "alert";

const GRADE_TONE: Record<Grade, Tone> = {
  "A+": "pass",
  A: "pass",
  B: "warn",
  C: "warn",
  D: "alert",
  E: "alert",
  F: "alert",
};

export function gradeTone(grade: Grade): Tone {
  return GRADE_TONE[grade];
}

const SEVERITY_TONE: Record<Severity, Tone | "neutral"> = {
  critical: "alert",
  high: "alert",
  medium: "warn",
  low: "neutral",
  info: "neutral",
};

export function severityTone(severity: Severity): Tone | "neutral" {
  return SEVERITY_TONE[severity];
}

const TONE_TEXT_CLASS: Record<Tone | "neutral", string> = {
  pass: "text-pass",
  warn: "text-warn",
  alert: "text-alert",
  neutral: "text-ink-muted",
};

const TONE_BG_CLASS: Record<Tone | "neutral", string> = {
  pass: "bg-pass/10 text-pass",
  warn: "bg-warn/10 text-warn",
  alert: "bg-alert/10 text-alert",
  neutral: "bg-line/40 text-ink-muted",
};

export function toneTextClass(tone: Tone | "neutral"): string {
  return TONE_TEXT_CLASS[tone];
}

export function toneBadgeClass(tone: Tone | "neutral"): string {
  return TONE_BG_CLASS[tone];
}

export function severityLabel(severity: Severity): string {
  return severity.charAt(0).toUpperCase() + severity.slice(1);
}

/** Reformats an ISO 8601 UTC timestamp the API already sent — never derives one. */
export function formatDateDisplay(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTimeDisplay(iso: string): string {
  const date = new Date(iso);
  return `${new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date)}, ${new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date)} UTC`;
}

export function formatIsoDateDisplay(isoDate: string): string {
  // isoDate is a plain "YYYY-MM-DD" (contract's IsoDate), not a datetime —
  // parse it as UTC explicitly so it doesn't shift a day in another timezone.
  return formatDateDisplay(`${isoDate}T00:00:00Z`);
}

/** §6.13: `amount_minor` is always an integer in minor units (paise/cents)
 * — this only reformats it for display, never rounds or recalculates. */
export function formatMoney(amountMinor: number, currency: Currency): string {
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amountMinor / 100);
}

export function truncateMiddle(value: string, keep = 6): string {
  if (value.length <= keep * 2 + 1) return value;
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}
