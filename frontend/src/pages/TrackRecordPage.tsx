import { useMemo } from "react";
import type { TrackedMatch, TrackRecord } from "../api/client";
import { useTrackRecord } from "../api/queries";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryState";
import { matchDay } from "../lib/format";
import { seriesOf } from "../lib/trackRecord";
import { LogLossChart } from "./track/LogLossChart";
import { ScoreTable } from "./track/ScoreTable";
import { TrackedMatchRow } from "./track/TrackedMatchRow";

export function TrackRecordPage() {
  const record = useTrackRecord();

  return (
    <>
      <header className="page-head">
        <p className="page-head__kicker">
          {record.data?.season ? `${record.data.season} season` : "Track record"}
        </p>
        <h1>Track record</h1>
        <p className="page-head__lede">
          Every prediction here was saved before kickoff and never changed afterwards, so this is
          an honest record of how the models did, next to the bookmaker.
        </p>
      </header>

      {record.isPending ? (
        <LoadingState label="Loading the track record" rows={6} />
      ) : record.isError ? (
        <ErrorState
          title="Couldn't load the track record"
          error={record.error}
          onRetry={() => record.refetch()}
        />
      ) : (
        <TrackRecordDetails record={record.data} />
      )}
    </>
  );
}

export function TrackRecordDetails({ record }: { record: TrackRecord }) {
  const series = useMemo(() => seriesOf(record), [record]);
  const byName = useMemo(() => new Map(series.map((s) => [s.name, s])), [series]);
  const days = useMemo(() => groupByDay(record.matches), [record.matches]);

  if (record.matches.length === 0) {
    return (
      <EmptyState title="No predictions saved yet">
        The worker saves each model's prediction in the day before kickoff. They appear here as
        soon as the first one is saved.
      </EmptyState>
    );
  }

  const shadows = record.models.filter((m) => m.role === "shadow").map((m) => m.version);

  return (
    <>
      {shadows.length > 0 && (
        <p className="notice" role="note">
          {record.live_version ? `${record.live_version} is the model you see on the site. ` : ""}
          {shadows.join(" and ")} {shadows.length === 1 ? "runs" : "run"} in shadow mode: saved
          and scored the same way, but never shown as a prediction.
        </p>
      )}

      <section className="panel" aria-labelledby="scores-heading">
        <div className="panel__title">
          <h2 id="scores-heading">Scores so far</h2>
          <span className="small muted">★ best in column</span>
        </div>
        {record.compared_matches === 0 ? (
          <p className="muted">
            Nothing to score yet: scores appear once a match with saved predictions has been
            played.
          </p>
        ) : (
          <ScoreTable
            scores={record.scores}
            series={series}
            caption={`${record.compared_matches} ${record.compared_matches === 1 ? "match" : "matches"} every model predicted before kickoff, with a result and bookmaker odds.`}
          />
        )}
        <ModelCounts record={record} />
      </section>

      {record.running.length > 0 && (
        <section className="panel" aria-labelledby="chart-heading">
          <div className="panel__title">
            <h2 id="chart-heading">Log loss over the season</h2>
          </div>
          <LogLossChart running={record.running} series={series} />
        </section>
      )}

      <section className="panel" aria-labelledby="predictions-heading">
        <div className="panel__title">
          <h2 id="predictions-heading">Predictions v results</h2>
          <span className="small muted">{record.matches.length} matches, newest first</span>
        </div>
        {days.map(([day, matches]) => (
          <section key={day} className="matchday" aria-label={matchDay(day)}>
            <h3 className="matchday__date">{matchDay(day)}</h3>
            <ul className="results">
              {matches.map((m) => (
                <TrackedMatchRow key={m.match_id} match={m} series={byName} />
              ))}
            </ul>
          </section>
        ))}
      </section>
    </>
  );
}

function ModelCounts({ record }: { record: TrackRecord }) {
  return (
    <ul className="counts">
      {record.models.map((m) => {
        const parts = [
          `${m.scored} scored`,
          `${m.pending} awaiting a result`,
          m.postponed > 0 ? `${m.postponed} postponed (not counted until played)` : null,
          m.late > 0 ? `${m.late} saved after kickoff (never counted)` : null,
        ].filter(Boolean);
        return (
          <li key={m.version} className="small muted">
            <strong>{m.version}</strong>: {parts.join(", ")}
          </li>
        );
      })}
    </ul>
  );
}

function groupByDay(matches: readonly TrackedMatch[]): [string, TrackedMatch[]][] {
  const byDay = new Map<string, TrackedMatch[]>();
  for (const m of matches) {
    const list = byDay.get(m.match_date);
    if (list) list.push(m);
    else byDay.set(m.match_date, [m]);
  }
  return [...byDay];
}
