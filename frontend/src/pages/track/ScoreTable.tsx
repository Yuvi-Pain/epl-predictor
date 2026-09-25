import type { TrackRecordScore } from "../../api/client";
import type { Series } from "../../lib/trackRecord";
import { METRICS, formatMetric } from "../model/MetricsTable";

/** Every model and the bookmaker, scored on the same matches. ★ marks the best in a column. */
export function ScoreTable({
  scores,
  series,
  caption,
}: {
  scores: readonly TrackRecordScore[];
  series: readonly Series[];
  caption: string;
}) {
  const labels = new Map(series.map((s) => [s.name, s]));
  const best = Object.fromEntries(
    METRICS.map((m) => {
      const values = scores.map((s) => s.metrics[m.key]);
      return [m.key, m.higherIsBetter ? Math.max(...values) : Math.min(...values)];
    }),
  );

  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={caption}>
      <table className="metrics">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Predictor</th>
            {METRICS.map((m) => (
              <th key={m.key} scope="col">
                {m.label}
                <small>{m.hint}</small>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {scores.map((score) => {
            const s = labels.get(score.name);
            return (
              <tr key={score.name} className={s?.tone === "live" ? "metrics__model" : undefined}>
                <th scope="row">
                  <span className={`chart__swatch chart__swatch--${s?.tone ?? "shadow"}`} aria-hidden="true" />
                  {s?.label ?? score.name}
                </th>
                {METRICS.map((m) => {
                  const value = score.metrics[m.key];
                  const isBest = value === best[m.key];
                  return (
                    <td key={m.key} className={isBest ? "metrics__best" : undefined}>
                      {formatMetric(m.key, value)}
                      {isBest && <span className="visually-hidden"> (best)</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
