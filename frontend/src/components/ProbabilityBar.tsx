import type { Outcome, OutcomeProbabilities } from "../api/client";
import { OUTCOME_ORDER, outcomeLabel, pct } from "../lib/format";

interface Props {
  probabilities: OutcomeProbabilities;
  home: string;
  away: string;
  mostLikely: Outcome;
  compact?: boolean;
}

/**
 * Home win / draw / away win as one split bar with a legend underneath. The
 * legend carries the numbers and labels, so nothing depends on colour alone.
 */
export function ProbabilityBar({ probabilities, home, away, mostLikely, compact = false }: Props) {
  const summary = OUTCOME_ORDER.map(
    (o) => `${outcomeLabel(o, home, away)} ${pct(probabilities[o])}`,
  ).join(", ") + `. Most likely: ${outcomeLabel(mostLikely, home, away)}.`;

  return (
    <figure className={`probability${compact ? " probability--compact" : ""}`} style={{ margin: 0 }}>
      <div className="probability__track" role="img" aria-label={summary}>
        {OUTCOME_ORDER.map((o) => (
          <span
            key={o}
            className={`probability__segment probability__segment--${o}`}
            style={{ flexGrow: probabilities[o] }}
          />
        ))}
      </div>
      {!compact && (
        <ul className="probability__legend" aria-hidden="true">
          {OUTCOME_ORDER.map((o) => (
            <li
              key={o}
              className={`probability__key probability__key--${o}${o === mostLikely ? " probability__key--top" : ""}`}
            >
              <span className="probability__value">{pct(probabilities[o])}</span>
              <span className="probability__label">
                {outcomeLabel(o, home, away)}
                {o === mostLikely && " · most likely"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}
