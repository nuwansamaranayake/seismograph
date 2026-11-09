import { pct } from "@/lib/format";
import { type Box, linear, polyline, round, ticks, yCeiling } from "@/lib/scale";
import type { Chart } from "@/lib/types";

const BOX: Box = { width: 760, height: 260, left: 52, right: 16, top: 16, bottom: 30 };

/**
 * A control chart of one per-run series.
 *
 * The first `baseline_needed` runs set the limits and are drawn hollow, on a shaded band:
 * they are never judged. Limits are drawn only once the chart is warm. Before that the
 * chart shows the raw points and says how many runs are still needed. A line drawn early
 * would be a limit nobody computed.
 */
export function ControlChart({
  title,
  values,
  chart,
  tolerance,
  toleranceLabel,
}: {
  title: string;
  values: number[];
  chart: Chart;
  tolerance?: number;
  toleranceLabel?: string;
}) {
  if (values.length === 0) {
    return (
      <div className="card">
        <span className="label">{title}</span>
        <p className="dim">No runs yet. Launch a run to start the baseline.</p>
      </div>
    );
  }
  const first = chart.points[0];
  const limits = first ? [first.ucl, first.center] : [];
  const top = yCeiling(values, [...limits, tolerance ?? 0]);
  const plotRight = BOX.width - BOX.right;
  const plotBottom = BOX.height - BOX.bottom;
  const x = linear(0, Math.max(values.length - 1, 1), BOX.left, plotRight);
  const y = linear(0, top, plotBottom, BOX.top);
  const alarmAt = new Map(chart.points.map((p) => [p.t, p]));
  const alarms = chart.points.filter((p) => p.alarm);
  const baselineEnd = Math.min(chart.baseline_needed, values.length) - 1;

  return (
    <div className="card">
      <div className="row spread">
        <span className="label">{title}</span>
        {chart.warm ? (
          <span className={`badge ${alarms.length ? "block" : "pass"}`}>
            {alarms.length ? `${alarms.length} signal${alarms.length === 1 ? "" : "s"}` : "in control"}
          </span>
        ) : (
          <span className="badge">warming · {chart.runs_until_warm} more run{chart.runs_until_warm === 1 ? "" : "s"}</span>
        )}
      </div>
      <svg className="chart" viewBox={`0 0 ${BOX.width} ${BOX.height}`} role="img" aria-label={`${title} control chart`}>
        <rect
          className="baseline-band"
          x={BOX.left}
          y={BOX.top}
          width={round(x(Math.max(baselineEnd, 0)) - BOX.left)}
          height={plotBottom - BOX.top}
        />
        <text x={BOX.left + 4} y={BOX.top + 11}>
          baseline
        </text>
        {ticks(top).map((tick) => (
          <g key={tick}>
            <line className="grid-line" x1={BOX.left} x2={plotRight} y1={round(y(tick))} y2={round(y(tick))} />
            <text x={BOX.left - 6} y={round(y(tick)) + 3} textAnchor="end">
              {pct(tick, top < 0.1 ? 1 : 0)}
            </text>
          </g>
        ))}
        {first ? (
          <>
            <line className="limit" data-line="ucl" x1={BOX.left} x2={plotRight} y1={round(y(first.ucl))} y2={round(y(first.ucl))} />
            <line className="center" data-line="center" x1={BOX.left} x2={plotRight} y1={round(y(first.center))} y2={round(y(first.center))} />
            {first.lcl > 0 ? (
              <line className="limit" data-line="lcl" x1={BOX.left} x2={plotRight} y1={round(y(first.lcl))} y2={round(y(first.lcl))} />
            ) : null}
          </>
        ) : null}
        {tolerance !== undefined ? (
          <line className="tolerance" data-line="tolerance" x1={BOX.left} x2={plotRight} y1={round(y(tolerance))} y2={round(y(tolerance))} />
        ) : null}
        <polyline className="series" points={polyline(values.map((v, i) => [x(i), y(v)]))} />
        {values.map((v, i) => {
          const point = alarmAt.get(i);
          const kind = point?.alarm ? "alarm" : point ? "judged" : "";
          return (
            <g key={i}>
              {point?.alarm ? <circle className="ring" cx={round(x(i))} cy={round(y(v))} r="5" /> : null}
              <circle className={`dot ${kind}`.trim()} cx={round(x(i))} cy={round(y(v))} r="3.2">
                <title>
                  run {i}: {pct(v)}
                  {point?.rule ? ` · signal ${point.rule}` : ""}
                </title>
              </circle>
            </g>
          );
        })}
        <text x={BOX.left} y={BOX.height - 8}>
          run 0
        </text>
        <text x={plotRight} y={BOX.height - 8} textAnchor="end">
          run {values.length - 1}
        </text>
      </svg>
      <div className="legend">
        <span>
          <i />
          per-run value
        </span>
        {chart.warm ? (
          <>
            <span>
              <i className="gold" />
              control limit, 3 sigma from the baseline
            </span>
            <span>
              <i className="dimline" />
              baseline mean
            </span>
          </>
        ) : null}
        {tolerance !== undefined ? (
          <span>
            <i className="red" />
            {toleranceLabel ?? "declared tolerance"} {pct(tolerance)}
          </span>
        ) : null}
      </div>
      {alarms.length ? (
        <p className="msg err">
          Signal at run {alarms.map((p) => p.t).join(", ")}.{" "}
          {alarms.some((p) => p.rule === "run8")
            ? "we1 is a point beyond the limit. run8 is eight points in a row on one side of the mean."
            : "A point beyond the control limit is a change in the process, not noise."}
        </p>
      ) : null}
    </div>
  );
}
