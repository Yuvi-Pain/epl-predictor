import type { Outcome } from "../api/client";

export function pct(p: number, digits = 0): string {
  return `${(p * 100).toFixed(digits)}%`;
}

export function num(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : n.toFixed(digits);
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "2026-10-04" -> "Sun 4 Oct 2026". Parsed as UTC so the day never shifts. */
export function matchDay(isoDate: string): string {
  // Assembled from parts: whether there is a comma after the weekday varies
  // between ICU versions (browsers, Node releases).
  const parts = dayFormat.formatToParts(new Date(`${isoDate.slice(0, 10)}T00:00:00Z`));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month")} ${part("year")}`;
}

export function outcomeLabel(outcome: Outcome, home: string, away: string): string {
  switch (outcome) {
    case "home_win":
      return `${home} win`;
    case "away_win":
      return `${away} win`;
    case "draw":
      return "Draw";
  }
}

export const OUTCOME_ORDER: readonly Outcome[] = ["home_win", "draw", "away_win"];

const kickoffFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/London",
});

/** "2026-10-10T11:30:00Z" -> "12:30": kick-off in UK time, whatever the viewer's timezone. */
export function kickoffTime(isoDateTime: string): string {
  return kickoffFormat.format(new Date(isoDateTime));
}
