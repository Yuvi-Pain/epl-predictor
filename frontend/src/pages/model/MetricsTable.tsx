import type { Metrics, SplitMetrics } from "../../api/client";
import { pct } from "../../lib/format";

type MetricKey = keyof Metrics;

export const METRICS: { key: MetricKey; label: string; hint: string; higherIsBetter: boolean }[] = [
  { key: "accuracy", label: "Accuracy", hint: "top pick right, higher is better", higherIsBetter: true },
  { key: "log_loss", label: "Log loss", hint: "confidence penalty, lower is better", higherIsBetter: false },
  { key: "brier", label: "Brier", hint: "probability error, lower is better", higherIsBetter: false },
];

export const MODEL_ROW = "This model";

export interface MetricRow {
  name: string;
  metrics: Metrics;
  isModel: boolean;
}

export function metricRows(split: SplitMetrics): MetricRow[] {
  return [
    { name: MODEL_ROW, metrics: split.model, isModel: true },
    ...Object.entries(split.baselines).map(([name, metrics]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      metrics,
      isModel: false,
    })),
  ];
}

export function formatMetric(key: MetricKey, value: number): string {
  return key === "accuracy" ? pct(value, 1) : value.toFixed(3);
}

function bestValue(rows: MetricRow[], key: MetricKey, higherIsBetter: boolean): number {
  const values = rows.map((r) => r.metrics[key]);
  return higherIsBetter ? Math.max(...values) : Math.min(...values);
}

export function MetricsTable({ split, caption }: { split: SplitMetrics; caption: string }) {
  const rows = metricRows(split);
  const best = Object.fromEntries(
    METRICS.map((m) => [m.key, bestValue(rows, m.key, m.higherIsBetter)]),
  ) as Record<MetricKey, number>;

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
          {rows.map((row) => (
            <tr key={row.name} className={row.isModel ? "metrics__model" : undefined}>
              <th scope="row">{row.name}</th>
              {METRICS.map((m) => {
                const value = row.metrics[m.key];
                const isBest = value === best[m.key];
                return (
                  <td key={m.key} className={isBest ? "metrics__best" : undefined}>
                    {formatMetric(m.key, value)}
                    {isBest && <span className="visually-hidden"> (best)</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
