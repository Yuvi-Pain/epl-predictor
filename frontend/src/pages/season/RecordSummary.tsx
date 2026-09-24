import type { SeasonRecord } from "../../lib/record";
import { pct } from "../../lib/format";

const W = 100;
const H = 40;

/** The headline record plus a line of running accuracy over the season. */
export function RecordSummary({ record }: { record: SeasonRecord }) {
  const { correct, played, homeWinRate, points } = record;
  const accuracy = played ? correct / played : 0;

  return (
    <div className="record">
      <div className="record__score">
        <p className="record__big">
          {correct}
          <small>/{played}</small>
        </p>
        <p>
          <strong>{pct(accuracy)}</strong> of the model's top picks were right.
        </p>
        <p className="small muted">
          Always picking the home side would have been right {pct(homeWinRate)} of the time.
        </p>
      </div>
      {points.length > 1 && (
        <figure style={{ margin: 0, display: "grid", gap: "var(--space-2)" }}>
          <Sparkline record={record} />
          <figcaption className="sparkline-caption">
            <span>
              <span className="key-line" aria-hidden="true" />
              Running accuracy, match by match
            </span>
            <span>
              <span className="key-line key-line--ref" aria-hidden="true" />
              Home win rate ({pct(homeWinRate)})
            </span>
          </figcaption>
        </figure>
      )}
    </div>
  );
}

function Sparkline({ record }: { record: SeasonRecord }) {
  const { points, homeWinRate } = record;
  const x = (i: number) => (points.length === 1 ? 0 : (i / (points.length - 1)) * W);
  const y = (rate: number) => H - rate * H;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(p.correct / p.played).toFixed(2)}`)
    .join(" ");
  const first = points[0]!;
  const last = points[points.length - 1]!;
  const label =
    `Running accuracy over ${points.length} matches, from ${pct(first.correct / first.played)} ` +
    `after the first match to ${pct(last.correct / last.played)} now.`;

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      style={{ aspectRatio: "5 / 1" }}
    >
      <line className="sparkline__ref" x1={0} x2={W} y1={y(homeWinRate)} y2={y(homeWinRate)} />
      <path className="sparkline__line" d={path} />
    </svg>
  );
}
