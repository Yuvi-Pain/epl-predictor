import type { ModelInfo } from "../api/client";
import { useModelInfo } from "../api/queries";
import { ErrorState, LoadingState } from "../components/QueryState";
import { MetricsTable } from "./model/MetricsTable";
import { VersusBookmaker } from "./model/VersusBookmaker";

const FEATURE_LABELS: Record<string, string> = {
  home_elo: "Home Elo",
  away_elo: "Away Elo",
  home_form_points: "Home points (last 5)",
  home_form_goals_for: "Home goals scored",
  home_form_goals_against: "Home goals conceded",
  home_form_sot_for: "Home shots on target",
  home_form_sot_against: "Home shots on target faced",
  away_form_points: "Away points (last 5)",
  away_form_goals_for: "Away goals scored",
  away_form_goals_against: "Away goals conceded",
  away_form_sot_for: "Away shots on target",
  away_form_sot_against: "Away shots on target faced",
};

export function ModelPage() {
  const model = useModelInfo();

  return (
    <>
      <header className="page-head">
        <p className="page-head__kicker">Under the hood</p>
        <h1>The model</h1>
        <p className="page-head__lede">
          A multinomial logistic regression on Elo ratings and recent form, scored on a season it
          never saw and compared with simple baselines and the bookmaker.
        </p>
      </header>

      {model.isPending ? (
        <LoadingState label="Loading model details" rows={5} />
      ) : model.isError ? (
        <ErrorState
          title="No model details"
          error={model.error}
          onRetry={() => model.refetch()}
        />
      ) : (
        <ModelDetails info={model.data} />
      )}
    </>
  );
}

function seasonRange(seasons: readonly string[]): string {
  if (seasons.length === 0) return "—";
  if (seasons.length === 1) return seasons[0]!;
  return `${seasons[0]} – ${seasons[seasons.length - 1]}`;
}

function trainedOn(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function ModelDetails({ info }: { info: ModelInfo }) {
  return (
    <>
      <section className="panel" aria-labelledby="version-heading">
        <div className="panel__title">
          <h2 id="version-heading">Version {info.version}</h2>
        </div>
        <dl className="facts">
          <div>
            <dt>Trained</dt>
            <dd>{trainedOn(info.trained_at)}</dd>
          </div>
          <div>
            <dt>Learned from</dt>
            <dd>{seasonRange(info.train_seasons)}</dd>
          </div>
          <div>
            <dt>Tuned on</dt>
            <dd>{info.validation.season}</dd>
          </div>
          <div>
            <dt>Tested on</dt>
            <dd>{info.test.season}</dd>
          </div>
        </dl>
      </section>

      <section className="panel" aria-labelledby="bookmaker-heading">
        <div className="panel__title">
          <h2 id="bookmaker-heading">Against the bookmaker</h2>
        </div>
        <VersusBookmaker split={info.test} />
      </section>

      <section className="panel" aria-labelledby="test-heading">
        <div className="panel__title">
          <h2 id="test-heading">Test scores</h2>
          <span className="small muted">★ best in column</span>
        </div>
        <MetricsTable
          split={info.test}
          caption={`${info.test.season}: held back from training and tuning, so an honest score.`}
        />
        <details>
          <summary>Validation scores ({info.validation.season})</summary>
          <MetricsTable
            split={info.validation}
            caption={`${info.validation.season}: used to choose the regularisation strength.`}
          />
        </details>
      </section>

      <section className="panel" aria-labelledby="features-heading">
        <div className="panel__title">
          <h2 id="features-heading">Inputs</h2>
          <span className="small muted">{info.features.length} features</span>
        </div>
        <ul className="feature-list">
          {info.features.map((f) => (
            <li key={f}>{FEATURE_LABELS[f] ?? f}</li>
          ))}
        </ul>
      </section>
    </>
  );
}
