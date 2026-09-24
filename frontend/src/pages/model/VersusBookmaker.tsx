import type { SplitMetrics } from "../../api/client";
import { pct } from "../../lib/format";
import { MODEL_ROW, metricRows } from "./MetricsTable";

/** The bookmaker's odds (margin removed) are the bar to beat. */
export function bookmakerKey(split: SplitMetrics): string | undefined {
  return Object.keys(split.baselines).find((k) => k.toLowerCase().includes("bookmaker"));
}

export function bookmakerVerdict(split: SplitMetrics): string | null {
  const key = bookmakerKey(split);
  const bookie = key ? split.baselines[key] : undefined;
  if (!bookie) return null;
  const gap = split.model.log_loss - bookie.log_loss;
  if (Math.abs(gap) < 0.0005) {
    return `On ${split.season}, the model matched the bookmaker's log loss almost exactly.`;
  }
  return gap < 0
    ? `On ${split.season}, the model beat the bookmaker on log loss by ${Math.abs(gap).toFixed(3)}.`
    : `On ${split.season}, the bookmaker's odds were better calibrated: their log loss was ${gap.toFixed(3)} lower than the model's.`;
}

export function VersusBookmaker({ split }: { split: SplitMetrics }) {
  const verdict = bookmakerVerdict(split);
  const rows = metricRows(split).sort((a, b) => b.metrics.accuracy - a.metrics.accuracy);

  return (
    <div className="versus">
      <p>
        {verdict ??
          "No bookmaker baseline for this season: some matches were missing odds."}{" "}
        <span className="muted">
          Bookmakers are hard to beat: their prices use team news, injuries and market money that
          this model never sees.
        </span>
      </p>
      <h3>Accuracy on {split.season}</h3>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: "var(--space-3)" }}>
        {rows.map((row) => (
          <li
            key={row.name}
            className={`versus__row${row.name === MODEL_ROW ? " versus__row--model" : ""}`}
          >
            <span>{row.name}</span>
            <span className="versus__track" aria-hidden="true">
              <span
                className="versus__fill"
                style={{ display: "block", width: pct(row.metrics.accuracy, 1) }}
              />
            </span>
            <span className="versus__value">{pct(row.metrics.accuracy, 1)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
