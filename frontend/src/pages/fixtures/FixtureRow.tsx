import { Link } from "react-router";
import type { UpcomingFixture } from "../../api/client";
import { ProbabilityBar } from "../../components/ProbabilityBar";
import { TeamName } from "../../components/TeamBadge";
import { OUTCOME_ORDER, kickoffTime, pct } from "../../lib/format";

export function predictPath(home: number, away: number): string {
  return `/predict?${new URLSearchParams({ home: String(home), away: String(away) })}`;
}

/**
 * One upcoming match: kick-off, the two teams and the model's chances. The
 * whole row links to the Predict page for that pairing, which shows the Elo
 * and form numbers behind the prediction.
 */
export function FixtureRow({ fixture }: { fixture: UpcomingFixture }) {
  const home = fixture.home_team.name;
  const away = fixture.away_team.name;
  const { probabilities, most_likely } = fixture.prediction;

  return (
    <li>
      <Link
        className="upcoming"
        to={predictPath(fixture.home_team.id, fixture.away_team.id)}
      >
        <span className="upcoming__time">
          {fixture.kickoff ? (
            <time dateTime={fixture.kickoff}>{kickoffTime(fixture.kickoff)}</time>
          ) : (
            <span className="muted">TBC</span>
          )}
        </span>

        <span className="upcoming__teams">
          <TeamName name={home} />
          <span className="visually-hidden"> v </span>
          <TeamName name={away} />
        </span>

        <span className="upcoming__chances">
          <ProbabilityBar
            probabilities={probabilities}
            mostLikely={most_likely}
            home={home}
            away={away}
            compact
          />
          {/* The bar's label already reads these out; this row is for sighted users. */}
          <span className="upcoming__numbers" aria-hidden="true">
            {OUTCOME_ORDER.map((o) => (
              <span
                key={o}
                className={`upcoming__number upcoming__number--${o}${o === most_likely ? " upcoming__number--top" : ""}`}
              >
                {pct(probabilities[o])}
              </span>
            ))}
          </span>
        </span>

        <span className="upcoming__go" aria-hidden="true">
          ›
        </span>
      </Link>
    </li>
  );
}
