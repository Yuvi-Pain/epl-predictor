import { useSearchParams } from "react-router";
import type { PredictResponse } from "../api/client";
import { usePrediction, useTeams } from "../api/queries";
import { ProbabilityBar } from "../components/ProbabilityBar";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryState";
import { TeamBadge } from "../components/TeamBadge";
import { matchDay } from "../lib/format";
import { FeatureComparison, eloSummary } from "./predict/FeatureComparison";
import { TeamPicker } from "./predict/TeamPicker";

function readId(params: URLSearchParams, key: string): number | null {
  const n = Number(params.get(key));
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function PredictPage() {
  // The chosen teams live in the URL (?home=1&away=17), so a prediction can be
  // bookmarked or shared and the back button undoes a change.
  const [params, setParams] = useSearchParams();
  const home = readId(params, "home");
  const away = readId(params, "away");
  const teams = useTeams();

  const choose = (h: number | null, a: number | null) => {
    const next = new URLSearchParams();
    if (h !== null) next.set("home", String(h));
    if (a !== null) next.set("away", String(a));
    setParams(next, { replace: true });
  };

  return (
    <>
      <header className="page-head">
        <p className="page-head__kicker">Match predictor</p>
        <h1>Who wins?</h1>
        <p className="page-head__lede">
          Pick a fixture to see the model's win, draw and loss chances, built only from results
          before today.
        </p>
      </header>

      <section className="panel" aria-labelledby="fixture-heading">
        <h2 id="fixture-heading" className="visually-hidden">
          Choose a fixture
        </h2>
        {teams.isPending ? (
          <LoadingState label="Loading teams" rows={1} />
        ) : teams.isError ? (
          <ErrorState title="Couldn't load teams" error={teams.error} onRetry={() => teams.refetch()} />
        ) : teams.data.teams.length === 0 ? (
          <EmptyState title="No teams yet">
            Load results first: <code>python -m scripts.load_history</code>
          </EmptyState>
        ) : (
          <TeamPicker teams={teams.data.teams} home={home} away={away} onChange={choose} />
        )}
      </section>

      {teams.isSuccess && teams.data.teams.length > 0 && (
        <PredictionPanel home={home} away={away} />
      )}
    </>
  );
}

function PredictionPanel({ home, away }: { home: number | null; away: number | null }) {
  const prediction = usePrediction(home, away);

  if (home === null || away === null) {
    return (
      <EmptyState title="Pick two teams">
        Choose a home and an away side above and the prediction appears here.
      </EmptyState>
    );
  }
  if (prediction.isPending) return <LoadingState label="Working out the prediction" />;
  if (prediction.isError) {
    return (
      <ErrorState
        title="Couldn't get a prediction"
        error={prediction.error}
        onRetry={() => prediction.refetch()}
      />
    );
  }
  return <PredictionResult data={prediction.data} />;
}

export function PredictionResult({ data }: { data: PredictResponse }) {
  const home = data.home_team.name;
  const away = data.away_team.name;
  return (
    <>
      <section className="panel" aria-labelledby="prediction-heading" aria-live="polite">
        <div className="panel__title">
          <h2 id="prediction-heading">Prediction</h2>
          <span className="small muted">
            Model {data.model_version} · results before {matchDay(data.as_of)}
          </span>
        </div>
        <div className="fixture">
          <div className="fixture__side">
            <TeamBadge name={home} size="lg" />
            <span className="fixture__name">{home}</span>
            <span className="fixture__role">Home</span>
          </div>
          <span className="fixture__vs" aria-hidden="true">
            v
          </span>
          <div className="fixture__side">
            <TeamBadge name={away} size="lg" />
            <span className="fixture__name">{away}</span>
            <span className="fixture__role">Away</span>
          </div>
        </div>
        <ProbabilityBar
          probabilities={data.prediction.probabilities}
          mostLikely={data.prediction.most_likely}
          home={home}
          away={away}
        />
      </section>

      <section className="panel" aria-labelledby="drivers-heading">
        <div className="panel__title">
          <h2 id="drivers-heading">What drove it</h2>
        </div>
        <p>{eloSummary(data.features, home, away)}</p>
        <FeatureComparison features={data.features} home={home} away={away} />
      </section>
    </>
  );
}
