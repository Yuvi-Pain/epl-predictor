import { Check, Cross } from "../../components/Icons";
import { ProbabilityBar } from "../../components/ProbabilityBar";
import { TeamName } from "../../components/TeamBadge";
import { outcomeLabel, pct } from "../../lib/format";
import type { RecordPoint } from "../../lib/record";

/** One played match: the score, the model's pre-match pick, and whether it was right. */
export function MatchRow({ point }: { point: RecordPoint }) {
  const { match, correct, played } = point;
  const home = match.home_team.name;
  const away = match.away_team.name;
  const { probabilities, most_likely } = match.prediction;

  return (
    <li className="result">
      <div className="result__teams">
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
      </div>

      <div className="result__pick">
        <span>
          <span className="muted">Model picked </span>
          <strong>{outcomeLabel(most_likely, home, away)}</strong>
          <span className="muted"> ({pct(probabilities[most_likely])})</span>
        </span>
        <ProbabilityBar
          probabilities={probabilities}
          mostLikely={most_likely}
          home={home}
          away={away}
          compact
        />
      </div>

      <div className="result__verdict">
        {match.correct ? (
          <span className="pill pill--good">
            <Check /> Right
          </span>
        ) : (
          <span className="pill pill--bad">
            <Cross /> Wrong
          </span>
        )}
        <span className="small muted">
          <span className="visually-hidden">Running record: </span>
          {correct}/{played}
        </span>
      </div>
    </li>
  );
}
