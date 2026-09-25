import type { OutcomeProbabilities, SavedPrediction, TrackedMatch } from "../../api/client";
import { Check, Cross } from "../../components/Icons";
import { TeamName } from "../../components/TeamBadge";
import { OUTCOME_ORDER, kickoffTime, outcomeLabel, pct } from "../../lib/format";
import { STATUS_LABEL, type Series } from "../../lib/trackRecord";

const savedAt = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/London",
});

function topPick(p: OutcomeProbabilities) {
  // Ties go to the first in home, draw, away order.
  return OUTCOME_ORDER.reduce((best, o) => (p[o] > p[best] ? o : best));
}

function Verdict({ prediction }: { prediction: SavedPrediction }) {
  if (prediction.status === "scored") {
    return prediction.correct ? (
      <span className="pill pill--good">
        <Check /> Right
      </span>
    ) : (
      <span className="pill pill--bad">
        <Cross /> Wrong
      </span>
    );
  }
  return <span className="pill pill--plain">{STATUS_LABEL[prediction.status]}</span>;
}

/** One match: the result (or when it kicks off), each model's frozen pick, and the bookmaker's. */
export function TrackedMatchRow({
  match,
  series,
}: {
  match: TrackedMatch;
  series: ReadonlyMap<string, Series>;
}) {
  const home = match.home_team.name;
  const away = match.away_team.name;

  return (
    <li className="tracked">
      <div className="result__teams">
        {match.score ? (
          <>
            <span className="visually-hidden">
              {home} {match.score.home_goals}, {away} {match.score.away_goals}.
            </span>
            <div
              className={`result__line${match.actual === "home_win" ? " result__winner" : ""}`}
              aria-hidden="true"
            >
              <TeamName name={home} />
              <span className="result__goals">{match.score.home_goals}</span>
            </div>
            <div
              className={`result__line${match.actual === "away_win" ? " result__winner" : ""}`}
              aria-hidden="true"
            >
              <TeamName name={away} />
              <span className="result__goals">{match.score.away_goals}</span>
            </div>
          </>
        ) : (
          <>
            <div className="result__line">
              <TeamName name={home} />
            </div>
            <div className="result__line">
              <TeamName name={away} />
            </div>
            {match.kickoff && (
              <span className="small muted">Kick-off {kickoffTime(match.kickoff)}</span>
            )}
          </>
        )}
      </div>

      <ul className="tracked__picks" aria-label="Predictions">
        {match.predictions.map((p) => {
          const s = series.get(p.model_version);
          const pick = p.prediction.most_likely;
          return (
            <li key={p.model_version} className="tracked__pick">
              <span className="tracked__who">
                <span className={`chart__swatch chart__swatch--${s?.tone ?? "shadow"}`} aria-hidden="true" />
                {s?.label ?? p.model_version}
              </span>
              <span>
                <strong>{outcomeLabel(pick, home, away)}</strong>
                <span className="muted"> ({pct(p.prediction.probabilities[pick])})</span>
                <span className="small muted tracked__when">
                  Saved {savedAt.format(new Date(p.predicted_at))}
                </span>
              </span>
              <Verdict prediction={p} />
            </li>
          );
        })}
        {match.bookmaker && (
          <li className="tracked__pick">
            <span className="tracked__who">
              <span className="chart__swatch chart__swatch--bookmaker" aria-hidden="true" />
              Bookmaker
            </span>
            <span>
              <strong>{outcomeLabel(topPick(match.bookmaker), home, away)}</strong>
              <span className="muted"> ({pct(match.bookmaker[topPick(match.bookmaker)])})</span>
            </span>
            <span />
          </li>
        )}
      </ul>
    </li>
  );
}
