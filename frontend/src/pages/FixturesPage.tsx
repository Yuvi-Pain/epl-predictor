import { useMemo } from "react";
import type { UpcomingFixture, UpcomingFixtures } from "../api/client";
import { useUpcomingFixtures } from "../api/queries";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryState";
import { matchDay } from "../lib/format";
import { FixtureRow } from "./fixtures/FixtureRow";

export function FixturesPage() {
  const upcoming = useUpcomingFixtures();
  const data = upcoming.data;

  return (
    <>
      <header className="page-head">
        <p className="page-head__kicker">
          {data?.matchday ? `${data.season} · Matchweek ${data.matchday}` : "Coming up"}
        </p>
        <h1>Next up</h1>
        <p className="page-head__lede">
          The model's win, draw and loss chances for every match in the next matchweek, built
          only from results so far. Pick a match to see the numbers behind it.
        </p>
      </header>

      {upcoming.isPending ? (
        <LoadingState label="Loading upcoming fixtures" rows={6} />
      ) : upcoming.isError ? (
        <ErrorState
          title="Couldn't load fixtures"
          error={upcoming.error}
          onRetry={() => upcoming.refetch()}
        />
      ) : (
        <FixtureList data={upcoming.data} />
      )}
    </>
  );
}

export function FixtureList({ data }: { data: UpcomingFixtures }) {
  const days = useMemo(() => groupByDay(data.fixtures), [data.fixtures]);

  if (data.fixtures.length === 0) {
    return (
      <EmptyState title="No upcoming fixtures yet">
        The worker fetches the fixture list from football-data.org a few times a day. Check that{" "}
        <code>FOOTBALL_DATA_API_KEY</code> is set in <code>.env</code>, or fetch it now with{" "}
        <code>python -m scripts.refresh_fixtures</code>.
      </EmptyState>
    );
  }

  return (
    <section className="panel" aria-labelledby="fixtures-heading">
      <div className="panel__title">
        <h2 id="fixtures-heading">Fixtures</h2>
        <span className="small muted">
          Model {data.model_version} · kick-off times are UK time
        </span>
      </div>
      <ul className="upcoming-key" aria-hidden="true">
        <li className="upcoming-key__item upcoming-key__item--home_win">Home win</li>
        <li className="upcoming-key__item upcoming-key__item--draw">Draw</li>
        <li className="upcoming-key__item upcoming-key__item--away_win">Away win</li>
      </ul>
      {days.map(([day, fixtures]) => (
        <section key={day} className="matchday" aria-label={matchDay(day)}>
          <h3 className="matchday__date">{matchDay(day)}</h3>
          <ul className="upcoming-list">
            {fixtures.map((f) => (
              <FixtureRow key={f.match_id} fixture={f} />
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

/** Fixtures arrive soonest first, so grouping keeps days and matches in order. */
function groupByDay(fixtures: readonly UpcomingFixture[]): [string, UpcomingFixture[]][] {
  const byDay = new Map<string, UpcomingFixture[]>();
  for (const f of fixtures) {
    const list = byDay.get(f.match_date);
    if (list) list.push(f);
    else byDay.set(f.match_date, [f]);
  }
  return [...byDay];
}
