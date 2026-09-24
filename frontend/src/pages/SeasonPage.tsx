import { useMemo } from "react";
import type { MatchList } from "../api/client";
import { useSeasonMatches } from "../api/queries";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryState";
import { matchDay } from "../lib/format";
import { type RecordPoint, seasonRecord } from "../lib/record";
import { MatchRow } from "./season/MatchRow";
import { RecordSummary } from "./season/RecordSummary";

export const CURRENT_SEASON = "2026-27";

const SPLIT_NOTICE: Partial<Record<MatchList["model_split"], string>> = {
  train:
    "The model was trained on this season's results, so these predictions look better than they would have been at the time.",
  validation:
    "This season was used to tune the model, so these predictions are slightly optimistic.",
};

export function SeasonPage() {
  const matches = useSeasonMatches(CURRENT_SEASON);

  return (
    <>
      <header className="page-head">
        <p className="page-head__kicker">{CURRENT_SEASON} season</p>
        <h1>Predicted v actual</h1>
        <p className="page-head__lede">
          Every match played so far, with what the model said beforehand. Each prediction only
          uses results from before that match, so it is exactly what the model would have said
          at the time.
        </p>
      </header>

      {matches.isPending ? (
        <LoadingState label="Loading this season's matches" rows={6} />
      ) : matches.isError ? (
        <ErrorState
          title="Couldn't load matches"
          error={matches.error}
          onRetry={() => matches.refetch()}
        />
      ) : (
        <SeasonResults data={matches.data} />
      )}
    </>
  );
}

export function SeasonResults({ data }: { data: MatchList }) {
  const record = useMemo(() => seasonRecord(data.matches), [data.matches]);
  // Newest matchday first; the running record was counted oldest first.
  const days = useMemo(() => groupByDay([...record.points].reverse()), [record.points]);
  const notice = SPLIT_NOTICE[data.model_split];

  if (data.matches.length === 0) {
    return (
      <EmptyState title="No matches played yet">
        Once results come in, rerun <code>python -m scripts.load_history</code> and they appear
        here.
      </EmptyState>
    );
  }

  return (
    <>
      {notice && (
        <p className="notice" role="note">
          {notice}
        </p>
      )}
      <section className="panel" aria-labelledby="record-heading">
        <div className="panel__title">
          <h2 id="record-heading">Running record</h2>
          <span className="small muted">Model {data.model_version}</span>
        </div>
        <RecordSummary record={record} />
      </section>

      <section className="panel" aria-labelledby="results-heading">
        <div className="panel__title">
          <h2 id="results-heading">Results</h2>
          <span className="small muted">{data.matches.length} matches, newest first</span>
        </div>
        {days.map(([day, points]) => (
          <section key={day} className="matchday" aria-label={matchDay(day)}>
            <h3 className="matchday__date">{matchDay(day)}</h3>
            <ul className="results">
              {points.map((p) => (
                <MatchRow key={p.match.match_id} point={p} />
              ))}
            </ul>
          </section>
        ))}
      </section>
    </>
  );
}

function groupByDay(points: readonly RecordPoint[]): [string, RecordPoint[]][] {
  const byDay = new Map<string, RecordPoint[]>();
  for (const p of points) {
    const list = byDay.get(p.match.match_date);
    if (list) list.push(p);
    else byDay.set(p.match.match_date, [p]);
  }
  return [...byDay];
}
