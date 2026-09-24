import type { MatchFeatures } from "../../api/client";
import { num } from "../../lib/format";

type Side = "home" | "away";

interface Row {
  label: string;
  hint: string;
  home: number | null;
  away: number | null;
  /** Range the bars are drawn over. Values outside it are clamped. */
  range: [number, number];
  higherIsBetter: boolean;
  digits: number;
}

function rows(f: MatchFeatures): Row[] {
  return [
    { label: "Elo rating", hint: "long-run strength", home: f.home_elo, away: f.away_elo, range: [1300, 1800], higherIsBetter: true, digits: 0 },
    { label: "Points", hint: "per game, last 5", home: f.home_form_points, away: f.away_form_points, range: [0, 3], higherIsBetter: true, digits: 1 },
    { label: "Goals scored", hint: "per game, last 5", home: f.home_form_goals_for, away: f.away_form_goals_for, range: [0, 3], higherIsBetter: true, digits: 1 },
    { label: "Goals conceded", hint: "per game, last 5", home: f.home_form_goals_against, away: f.away_form_goals_against, range: [0, 3], higherIsBetter: false, digits: 1 },
    { label: "Shots on target", hint: "per game, last 5", home: f.home_form_sot_for, away: f.away_form_sot_for, range: [0, 8], higherIsBetter: true, digits: 1 },
    { label: "Shots on target faced", hint: "per game, last 5", home: f.home_form_sot_against, away: f.away_form_sot_against, range: [0, 8], higherIsBetter: false, digits: 1 },
  ];
}

function edge(row: Row): Side | null {
  if (row.home === null || row.away === null) return null;
  const home = Number(row.home.toFixed(row.digits));
  const away = Number(row.away.toFixed(row.digits));
  if (home === away) return null;
  return home > away === row.higherIsBetter ? "home" : "away";
}

function fill(value: number | null, [lo, hi]: [number, number]): string {
  if (value === null) return "0%";
  const t = Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
  return `${Math.round(t * 100)}%`;
}

/** One sentence on the biggest input, the Elo gap. */
export function eloSummary(f: MatchFeatures, home: string, away: string): string {
  const gap = Math.round(f.home_elo - f.away_elo);
  if (Math.abs(gap) < 10) return `${home} and ${away} are rated almost exactly level on Elo.`;
  const [stronger, weaker] = gap > 0 ? [home, away] : [away, home];
  return `${stronger} are rated ${Math.abs(gap)} Elo points above ${weaker}.`;
}

export function FeatureComparison({
  features,
  home,
  away,
}: {
  features: MatchFeatures;
  home: string;
  away: string;
}) {
  const all = rows(features);
  const hasGaps = all.some((r) => r.home === null || r.away === null);

  return (
    <div className="compare-wrap" style={{ display: "grid", gap: "var(--space-3)" }}>
      <div className="compare-head" aria-hidden="true">
        <span>{home}</span>
        <span>{away}</span>
      </div>
      <ul className="compare" style={{ listStyle: "none", padding: 0 }}>
        {all.map((row) => {
          const better = edge(row);
          return (
            <li key={row.label} className="compare__row">
              <span className="compare__label">
                <dfn>{row.label}</dfn> <span className="small">{row.hint}</span>
              </span>
              {(["home", "away"] as const).map((side) => (
                <p
                  key={side}
                  className={`compare__value compare__value--${side}${better === side ? " compare__value--edge" : ""}`}
                >
                  <span className="visually-hidden">{side === "home" ? home : away}: </span>
                  {num(row[side], row.digits)}
                  {better === side && <span className="visually-hidden"> (better)</span>}
                </p>
              ))}
              <div className="compare__bars" aria-hidden="true">
                <div className="compare__bar compare__bar--home">
                  <div className="compare__fill" style={{ width: fill(row.home, row.range) }} />
                </div>
                <div className="compare__bar compare__bar--away">
                  <div className="compare__fill" style={{ width: fill(row.away, row.range) }} />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {hasGaps && (
        <p className="small muted">
          — means the team has no earlier league matches in the data (newly promoted, say). The
          model fills those gaps with its training average.
        </p>
      )}
    </div>
  );
}
