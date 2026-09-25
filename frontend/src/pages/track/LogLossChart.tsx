import {
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { RunningLogLoss } from "../../api/client";
import { matchDay } from "../../lib/format";
import type { Series } from "../../lib/trackRecord";

// Drawn at the plot's real width in pixels (see usePlotWidth), so text stays
// legible on a phone instead of shrinking with the whole picture.
const DEFAULT_W = 640;
const H = 240;
const PAD = { top: 12, right: 96, bottom: 28, left: 44 };
const PLOT_H = H - PAD.top - PAD.bottom;
const LABEL_GAP = 14; // minimum vertical distance between end labels

const shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function dayMs(iso: string): number {
  return Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
}

/** Round tick values covering [lo, hi]: steps of 0.02, 0.05, 0.1, ... */
function ticks(lo: number, hi: number): number[] {
  const span = Math.max(hi - lo, 0.01);
  const step = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1].find((s) => span / s <= 6) ?? 1;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(Number(t.toFixed(4)));
  return out;
}

/** Push end labels apart so none overlap, keeping their order. */
function spreadLabels(ys: number[]): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < order.length; k++) {
    order[k]!.y = Math.max(order[k]!.y, order[k - 1]!.y + LABEL_GAP);
  }
  const out = [...ys];
  for (const { y, i } of order) out[i] = y;
  return out;
}

/** The width of an element in CSS pixels, kept up to date as it resizes. */
function usePlotWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(DEFAULT_W);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/**
 * Running mean log loss per model and for the bookmaker, one point per match
 * date. Lower is better. Hover, or focus and use the arrow keys, for the values
 * at a date; the same numbers are in the table below the chart.
 */
export function LogLossChart({
  running,
  series,
}: {
  running: readonly RunningLogLoss[];
  series: readonly Series[];
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const W = usePlotWidth(plotRef);
  const PLOT_W = W - PAD.left - PAD.right;
  const [active, setActive] = useState<number | null>(null);

  const geometry = useMemo(() => {
    const values = running.flatMap((p) => series.map((s) => p.log_loss[s.name] ?? NaN));
    const finite = values.filter(Number.isFinite);
    const lo = Math.min(...finite);
    const hi = Math.max(...finite);
    const pad = Math.max((hi - lo) * 0.1, 0.02);
    const yLo = lo - pad;
    const yHi = hi + pad;
    const t0 = dayMs(running[0]!.match_date);
    const t1 = dayMs(running[running.length - 1]!.match_date);
    const x = (iso: string) =>
      t1 === t0 ? PAD.left + PLOT_W / 2 : PAD.left + ((dayMs(iso) - t0) / (t1 - t0)) * PLOT_W;
    const y = (v: number) => PAD.top + ((yHi - v) / (yHi - yLo)) * PLOT_H;
    return { x, y, yTicks: ticks(yLo, yHi) };
  }, [running, series, PLOT_W]);

  const { x, y, yTicks } = geometry;
  const xs = running.map((p) => x(p.match_date));
  const last = running[running.length - 1]!;
  const endYs = spreadLabels(series.map((s) => y(last.log_loss[s.name] ?? 0)));

  function pick(clientX: number) {
    const svg = svgRef.current;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const vx = ((clientX - box.left) / box.width) * W;
    let best = 0;
    xs.forEach((px, i) => {
      if (Math.abs(px - vx) < Math.abs(xs[best]! - vx)) best = i;
    });
    setActive(best);
  }

  function onKeyDown(e: KeyboardEvent<SVGSVGElement>) {
    const lastIndex = running.length - 1;
    const current = active ?? lastIndex;
    const next =
      e.key === "ArrowLeft" ? Math.max(0, current - 1)
      : e.key === "ArrowRight" ? Math.min(lastIndex, current + 1)
      : e.key === "Home" ? 0
      : e.key === "End" ? lastIndex
      : null;
    if (next === null) return;
    e.preventDefault();
    setActive(next);
  }

  const point = active === null ? null : running[active]!;
  const summary = series
    .map((s) => `${s.label} ${(last.log_loss[s.name] ?? NaN).toFixed(3)}`)
    .join(", ");

  return (
    <figure className="chart">
      <ul className="chart__legend" aria-label="Lines">
        {series.map((s) => (
          <li key={s.name}>
            <span className={`chart__swatch chart__swatch--${s.tone}`} aria-hidden="true" />
            {s.label}
          </li>
        ))}
      </ul>

      <div className="chart__plot" ref={plotRef}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Running log loss over ${last.matches} matches up to ${matchDay(last.match_date)}: ${summary}. Lower is better. Use the arrow keys to read each date.`}
          tabIndex={0}
          onPointerMove={(e: PointerEvent<SVGSVGElement>) => pick(e.clientX)}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive(running.length - 1)}
          onBlur={() => setActive(null)}
          onKeyDown={onKeyDown}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line className="chart__grid" x1={PAD.left} x2={PAD.left + PLOT_W} y1={y(t)} y2={y(t)} />
              <text className="chart__tick" x={PAD.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
                {t.toFixed(2)}
              </text>
            </g>
          ))}
          <text className="chart__tick" x={xs[0]} y={H - 8} textAnchor={running.length > 1 ? "start" : "middle"}>
            {shortDate.format(dayMs(running[0]!.match_date))}
          </text>
          {running.length > 1 && (
            <text className="chart__tick" x={xs[xs.length - 1]} y={H - 8} textAnchor="end">
              {shortDate.format(dayMs(last.match_date))}
            </text>
          )}

          {point && (
            <line
              className="chart__crosshair"
              x1={xs[active!]}
              x2={xs[active!]}
              y1={PAD.top}
              y2={PAD.top + PLOT_H}
            />
          )}

          {series.map((s, i) => {
            const d = running
              .map((p, k) => `${k === 0 ? "M" : "L"}${xs[k]!.toFixed(1)},${y(p.log_loss[s.name] ?? 0).toFixed(1)}`)
              .join(" ");
            const endX = xs[xs.length - 1]!;
            return (
              <g key={s.name} className={`chart__series chart__series--${s.tone}`}>
                {running.length > 1 && <path className="chart__line" d={d} />}
                <circle className="chart__dot" cx={endX} cy={y(last.log_loss[s.name] ?? 0)} r={4} />
                {point && (
                  <circle
                    className="chart__dot"
                    cx={xs[active!]}
                    cy={y(point.log_loss[s.name] ?? 0)}
                    r={4}
                  />
                )}
                <line className="chart__label-key" x1={endX + 10} x2={endX + 22} y1={endYs[i]} y2={endYs[i]} />
                <text className="chart__label" x={endX + 26} y={endYs[i]} dominantBaseline="middle">
                  {s.name === "bookmaker" ? "Bookmaker" : s.name}
                </text>
              </g>
            );
          })}
        </svg>

        {point && (
          <div
            className="chart__tooltip"
            style={{ left: `${(xs[active!]! / W) * 100}%` }}
            data-flip={xs[active!]! > W / 2 ? "" : undefined}
            aria-hidden="true"
          >
            <p className="chart__tooltip-head">
              {matchDay(point.match_date)} · {point.matches} {point.matches === 1 ? "match" : "matches"}
            </p>
            <ul>
              {series.map((s) => (
                <li key={s.name}>
                  <span className={`chart__swatch chart__swatch--${s.tone}`} />
                  <strong>{(point.log_loss[s.name] ?? NaN).toFixed(3)}</strong>
                  <span className="muted">{s.label}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <figcaption className="small muted">
        Mean log loss over every compared match so far. Lower is better: it punishes confident
        predictions that turn out wrong.
      </figcaption>

      <details>
        <summary>Show as a table</summary>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Running log loss by date">
          <table className="metrics">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Matches</th>
                {series.map((s) => (
                  <th key={s.name} scope="col">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {running.map((p) => (
                <tr key={p.match_date}>
                  <th scope="row">{matchDay(p.match_date)}</th>
                  <td>{p.matches}</td>
                  {series.map((s) => (
                    <td key={s.name}>{(p.log_loss[s.name] ?? NaN).toFixed(3)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
