import type { PredictionStatus, TrackRecord } from "../api/client";

export const BOOKMAKER = "bookmaker";

/** One line on the chart and one row in the scores table: a model version or the bookmaker. */
export interface Series {
  name: string;
  label: string;
  /** CSS class suffix picking the series colour. Follows the entity, never its rank. */
  tone: "live" | "shadow" | "bookmaker";
}

/**
 * The live model, then the shadow models, then the bookmaker. The live model
 * always wears the first colour, a shadow the second, the bookmaker its own.
 */
export function seriesOf(record: TrackRecord): Series[] {
  const models: Series[] = record.models.map((m) => ({
    name: m.version,
    label: `${m.version} (${m.role})`,
    tone: m.role,
  }));
  return [...models, { name: BOOKMAKER, label: "Bookmaker", tone: "bookmaker" }];
}

export const STATUS_LABEL: Record<PredictionStatus, string> = {
  scored: "Scored",
  pending: "Awaiting result",
  postponed: "Postponed: not counted until played",
  late: "Saved after kickoff: never counted",
};
